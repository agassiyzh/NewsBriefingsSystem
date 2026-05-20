const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildEventPayload,
  buildTrackingUrl,
  bucketDwellDuration,
} = require('../../site/static/feedback.js');

test('buildEventPayload creates an item-level like payload with only whitelisted metadata', () => {
  const payload = buildEventPayload({
    eventType: 'like',
    channel: 'site',
    briefingId: '2026-05-19-08',
    itemId: '2026-05-19-08-001',
    anonymousId: 'anon_test_12345678',
    metadata: {
      source: 'Working Feed',
      tag: 'AI Agent',
      scope: 'item',
      forbidden: 'drop-me',
    },
  });

  assert.deepEqual(payload, {
    event_type: 'like',
    channel: 'site',
    briefing_id: '2026-05-19-08',
    item_id: '2026-05-19-08-001',
    anonymous_id: 'anon_test_12345678',
    metadata: {
      source: 'Working Feed',
      tag: 'AI Agent',
      scope: 'item',
    },
  });
});

test('buildEventPayload requires like and dislike events to target a news item', () => {
  for (const eventType of ['like', 'dislike']) {
    assert.throws(
      () =>
        buildEventPayload({
          eventType,
          channel: 'site',
          briefingId: '2026-05-19-08',
          anonymousId: 'anon_test_12345678',
        }),
      /item_id/i,
    );
  }
});

test('buildEventPayload requires click events to include a safe target URL', () => {
  assert.throws(
    () =>
      buildEventPayload({
        eventType: 'click',
        channel: 'site',
        briefingId: '2026-05-19-08',
        itemId: '2026-05-19-08-001',
        anonymousId: 'anon_test_12345678',
      }),
    /target_url/i,
  );
});

test('buildEventPayload rejects private or loopback IPv6 target URLs for click events', () => {
  assert.throws(
    () =>
      buildEventPayload({
        eventType: 'click',
        channel: 'site',
        briefingId: '2026-05-19-08',
        itemId: '2026-05-19-08-001',
        anonymousId: 'anon_test_12345678',
        targetUrl: 'https://[::1]/story',
      }),
    /private IP host/i,
  );
});

test('buildEventPayload allows explicit IPv6 loopback URLs for local dev http testing', () => {
  const payload = buildEventPayload({
    eventType: 'click',
    channel: 'site',
    briefingId: '2026-05-19-08',
    itemId: '2026-05-19-08-001',
    anonymousId: 'anon_test_12345678',
    targetUrl: 'http://[::1]:1313/story',
  });

  assert.equal(payload.target_url, 'http://[::1]:1313/story');
});

test('buildTrackingUrl encodes worker redirect URLs for known items without leaking anonymous identifiers', () => {
  const trackedUrl = buildTrackingUrl('http://127.0.0.1:8787', {
    targetUrl: 'https://example.com/story',
    briefingId: '2026-05-19-08',
    itemId: '2026-05-19-08-001',
    channel: 'site',
  });

  const parsed = new URL(trackedUrl);
  assert.equal(parsed.origin, 'http://127.0.0.1:8787');
  assert.equal(parsed.pathname, '/r');
  assert.equal(parsed.searchParams.get('u'), 'https://example.com/story');
  assert.equal(parsed.searchParams.get('briefing_id'), '2026-05-19-08');
  assert.equal(parsed.searchParams.get('item_id'), '2026-05-19-08-001');
  assert.equal(parsed.searchParams.get('channel'), 'site');
  assert.equal(parsed.searchParams.has('k'), false);
});

test('bucketDwellDuration returns coarse duration buckets', () => {
  assert.equal(bucketDwellDuration(4000), '0-10s');
  assert.equal(bucketDwellDuration(22000), '10-30s');
  assert.equal(bucketDwellDuration(118000), '30-120s');
  assert.equal(bucketDwellDuration(180000), '120s+');
});
