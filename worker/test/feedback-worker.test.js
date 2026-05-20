const test = require('node:test');
const assert = require('node:assert/strict');

const { handleRequest, createMemoryStore } = require('../src/index.js');

function createEnv() {
  return {
    ALLOWED_ORIGINS: 'http://localhost:1313,https://www.yuzhuohui.info',
    FEEDBACK_STORE: createMemoryStore(),
    FEEDBACK_VERSION: 'phase4-mvp',
  };
}

function createEventRequest(overrides = {}, { origin = 'http://localhost:1313' } = {}) {
  return new Request('http://worker.local/api/events', {
    method: 'POST',
    headers: {
      Origin: origin,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      event_type: 'like',
      channel: 'site',
      briefing_id: '2026-05-19-08',
      item_id: '2026-05-19-08-001',
      anonymous_id: 'anon_test_12345678',
      idempotency_key: 'idem-1',
      metadata: {
        source: 'Working Feed',
        scope: 'item',
      },
      ...overrides,
    }),
  });
}

function createValidEventRequest() {
  return createEventRequest();
}

async function readJson(response) {
  return JSON.parse(await response.text());
}

test('GET /api/health returns service metadata', async () => {
  const response = await handleRequest(new Request('http://worker.local/api/health'), createEnv());
  const payload = await readJson(response);

  assert.equal(response.status, 200);
  assert.deepEqual(payload, {
    ok: true,
    service: 'newsroom-feedback',
    version: 'phase4-mvp',
    allowed_origins: ['http://localhost:1313', 'https://www.yuzhuohui.info'],
  });
});

test('POST /api/events accepts valid payloads and deduplicates idempotency keys', async () => {
  const env = createEnv();
  const first = await handleRequest(createValidEventRequest(), env);
  const second = await handleRequest(createValidEventRequest(), env);
  const firstPayload = await readJson(first);
  const secondPayload = await readJson(second);

  assert.equal(first.status, 200);
  assert.equal(firstPayload.ok, true);
  assert.equal(firstPayload.duplicate, false);
  assert.match(firstPayload.event_id, /^evt_/);
  assert.equal(second.status, 200);
  assert.equal(secondPayload.ok, true);
  assert.equal(secondPayload.duplicate, true);
});

test('POST /api/events rejects unknown top-level fields', async () => {
  const env = createEnv();
  const response = await handleRequest(
    createEventRequest({
      email: 'reader@example.com',
    }, { origin: 'http://localhost:1313' }),
    env,
  );
  const payload = await readJson(response);

  assert.equal(response.status, 400);
  assert.equal(payload.ok, false);
  assert.equal(payload.error, 'unexpected_field:email');
  assert.equal(env.FEEDBACK_STORE.size(), 0);
});

test('POST /api/events rejects disallowed origins before writing', async () => {
  const env = createEnv();
  const response = await handleRequest(
    new Request('http://worker.local/api/events', {
      method: 'POST',
      headers: {
        Origin: 'https://evil.example',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        event_type: 'like',
        channel: 'site',
        briefing_id: '2026-05-19-08',
      }),
    }),
    env,
  );
  const payload = await readJson(response);

  assert.equal(response.status, 403);
  assert.equal(payload.ok, false);
  assert.equal(payload.error, 'invalid_origin');
  assert.equal(env.FEEDBACK_STORE.size(), 0);
});

test('GET /r rejects unsafe redirect targets', async () => {
  const response = await handleRequest(
    new Request('http://worker.local/r?u=javascript%3Aalert(1)&briefing_id=2026-05-19-08&item_id=2026-05-19-08-001&channel=site'),
    createEnv(),
  );

  assert.equal(response.status, 400);
  const body = await response.text();
  assert.match(body, /unsafe redirect/i);
});

test('GET /r rejects private and loopback IPv6 redirect targets', async () => {
  for (const targetUrl of ['https://[::1]/story', 'https://[fd00::1]/story']) {
    const response = await handleRequest(
      new Request(`http://worker.local/r?u=${encodeURIComponent(targetUrl)}&briefing_id=2026-05-19-08&item_id=2026-05-19-08-001&channel=site`),
      createEnv(),
    );

    assert.equal(response.status, 400);
    assert.match(await response.text(), /unsafe redirect/i);
  }
});

test('GET /f records feedback and returns thank-you HTML', async () => {
  const env = createEnv();
  const response = await handleRequest(
    new Request('http://worker.local/f?action=like&briefing_id=2026-05-19-08&item_id=2026-05-19-08-001&channel=site&anon=anon_test_12345678'),
    env,
  );

  assert.equal(response.status, 200);
  assert.match(await response.text(), /已记录，谢谢/);
  assert.equal(env.FEEDBACK_STORE.size(), 1);
});

test('GET /f refuses public-host fallback writes unless explicitly enabled', async () => {
  const env = createEnv();
  const response = await handleRequest(
    new Request('https://www.yuzhuohui.info/f?action=like&briefing_id=2026-05-19-08&item_id=2026-05-19-08-001&channel=site&anon=anon_test_12345678'),
    env,
  );

  assert.equal(response.status, 403);
  assert.match(await response.text(), /local-only|disabled/i);
  assert.equal(env.FEEDBACK_STORE.size(), 0);
});

test('GET /f allows IPv6 loopback hosts for local fallback verification', async () => {
  const env = createEnv();
  const response = await handleRequest(
    new Request('http://[::1]/f?action=like&briefing_id=2026-05-19-08&item_id=2026-05-19-08-001&channel=site&anon=anon_test_12345678'),
    env,
  );

  assert.equal(response.status, 200);
  assert.match(await response.text(), /已记录，谢谢/);
  assert.equal(env.FEEDBACK_STORE.size(), 1);
});

test('PUT /api/events returns method not allowed', async () => {
  const response = await handleRequest(new Request('http://worker.local/api/events', { method: 'PUT' }), createEnv());
  const payload = await readJson(response);

  assert.equal(response.status, 405);
  assert.equal(response.headers.get('Allow'), 'OPTIONS, POST');
  assert.deepEqual(payload, { ok: false, error: 'method_not_allowed' });
});
