const ALLOWED_EVENT_TYPES = new Set(['like', 'dislike', 'click', 'dwell', 'read']);
const ALLOWED_CHANNELS = new Set(['site', 'telegram', 'obsidian', 'manual', 'unknown']);
const ALLOWED_METADATA_KEYS = new Set(['source', 'tag', 'tags', 'scope', 'dwell_bucket', 'client_version']);
const ALLOWED_PAYLOAD_KEYS = new Set([
  'event_type',
  'channel',
  'briefing_id',
  'item_id',
  'anonymous_id',
  'duration_ms',
  'target_url',
  'metadata',
  'idempotency_key',
]);
const BRIEFING_ID_RE = /^\d{4}-\d{2}-\d{2}-(08|13|20|morning|noon|evening|monthly)$/;
const ITEM_ID_RE = /^\d{4}-\d{2}-\d{2}-(08|13|20)-\d{3}$/;
const ANON_ID_RE = /^anon_[A-Za-z0-9._:-]{8,128}$/;

function jsonResponse(payload, status = 200, headers = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      ...headers,
    },
  });
}

function htmlResponse(html, status = 200, headers = {}) {
  return new Response(html, {
    status,
    headers: {
      'content-type': 'text/html; charset=utf-8',
      ...headers,
    },
  });
}

function parseAllowedOrigins(env) {
  return String(env.ALLOWED_ORIGINS || '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);
}

function corsHeaders(origin, env) {
  return {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    Vary: 'Origin',
  };
}

function methodNotAllowed(allow) {
  return jsonResponse({ ok: false, error: 'method_not_allowed' }, 405, {
    Allow: allow,
  });
}

function isAllowedOrigin(origin, env) {
  if (!origin) {
    return false;
  }
  return parseAllowedOrigins(env).includes(origin);
}

function normalizeHostname(hostname) {
  return String(hostname || '').toLowerCase().replace(/^\[/, '').replace(/\]$/, '');
}

function isPrivateIpv4(hostname) {
  if (!/^\d+\.\d+\.\d+\.\d+$/.test(hostname)) {
    return false;
  }
  const [a, b] = hostname.split('.').map((part) => Number(part));
  return a === 10 || a === 127 || (a === 192 && b === 168) || (a === 172 && b >= 16 && b <= 31);
}

function isPrivateIpv6(hostname) {
  return hostname === '::'
    || hostname === '::1'
    || hostname === '0:0:0:0:0:0:0:1'
    || /^f[c-d][0-9a-f:]*$/i.test(hostname)
    || /^fe[89ab][0-9a-f:]*$/i.test(hostname);
}

function isPrivateOrLoopbackHost(hostname) {
  const normalized = normalizeHostname(hostname);
  const mappedIpv4 = normalized.startsWith('::ffff:') ? normalized.slice(7) : normalized;
  return isPrivateIpv4(mappedIpv4) || isPrivateIpv6(normalized);
}

function isLocalDevHost(hostname) {
  const normalized = normalizeHostname(hostname);
  return normalized === 'localhost'
    || normalized === '127.0.0.1'
    || normalized === '::1'
    || normalized === '0:0:0:0:0:0:0:1';
}

function isLocalFallbackHost(hostname) {
  const normalized = normalizeHostname(hostname);
  return normalized === 'worker.local'
    || isLocalDevHost(normalized)
    || isPrivateOrLoopbackHost(normalized);
}

function publicFallbackEnabled(env) {
  return String(env.ENABLE_PUBLIC_FEEDBACK_FALLBACK || '').toLowerCase() === 'true';
}

function sanitizeString(value, maxLength) {
  if (typeof value !== 'string') {
    return undefined;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  return trimmed.slice(0, maxLength);
}

function sanitizeMetadata(metadata) {
  if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) {
    return undefined;
  }

  const cleaned = {};
  for (const [key, value] of Object.entries(metadata)) {
    if (!ALLOWED_METADATA_KEYS.has(key)) {
      continue;
    }
    if (key === 'tags') {
      if (!Array.isArray(value)) {
        continue;
      }
      const tags = value.map((entry) => sanitizeString(entry, 50)).filter(Boolean).slice(0, 5);
      if (tags.length > 0) {
        cleaned.tags = tags;
      }
      continue;
    }
    const maxLength = key === 'source' ? 100 : 50;
    const sanitized = sanitizeString(value, maxLength);
    if (sanitized) {
      cleaned[key] = sanitized;
    }
  }

  if (!Object.keys(cleaned).length) {
    return undefined;
  }
  if (JSON.stringify(cleaned).length > 1024) {
    throw new Error('invalid_metadata');
  }
  return cleaned;
}

function normalizeTargetUrl(targetUrl) {
  if (typeof targetUrl !== 'string' || !targetUrl.trim()) {
    throw new Error('invalid_target_url');
  }
  const parsed = new URL(targetUrl);
  const protocol = parsed.protocol.toLowerCase();
  const hostname = normalizeHostname(parsed.hostname);
  if (protocol === 'https:') {
    if (isPrivateOrLoopbackHost(hostname)) {
      throw new Error('invalid_target_url');
    }
    return parsed.toString();
  }
  if (protocol === 'http:' && isLocalDevHost(hostname)) {
    return parsed.toString();
  }
  throw new Error('invalid_target_url');
}

function normalizeDuration(value) {
  if (value == null) {
    return undefined;
  }
  const duration = Number(value);
  if (!Number.isInteger(duration) || duration < 0 || duration > 30 * 60 * 1000) {
    throw new Error('invalid_duration_ms');
  }
  return duration;
}

function stableStringify(value) {
  return JSON.stringify(value, Object.keys(value).sort());
}

function fnv1aHex(input) {
  let hash = 0x811c9dc5;
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, '0');
}

function deriveIdempotencyKey(payload) {
  return fnv1aHex(stableStringify({
    event_type: payload.event_type,
    channel: payload.channel,
    anonymous_id: payload.anonymous_id || null,
    briefing_id: payload.briefing_id,
    item_id: payload.item_id || null,
    target_url: payload.target_url || null,
    duration_ms: payload.duration_ms || null,
    time_bucket: payload.time_bucket || null,
  }));
}

function randomHex(length = 16) {
  const bytes = new Uint8Array(Math.ceil(length / 2));
  if (globalThis.crypto && typeof globalThis.crypto.getRandomValues === 'function') {
    globalThis.crypto.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('').slice(0, length);
}

function deriveTimeBucket(payload) {
  const now = payload.now instanceof Date ? payload.now : new Date();
  const year = now.getUTCFullYear();
  const month = String(now.getUTCMonth() + 1).padStart(2, '0');
  const day = String(now.getUTCDate()).padStart(2, '0');
  const hour = String(now.getUTCHours()).padStart(2, '0');
  const minute = String(now.getUTCMinutes()).padStart(2, '0');

  if (payload.event_type === 'click') {
    return `${year}${month}${day}${hour}${minute}`;
  }
  if (payload.event_type === 'dwell') {
    return sanitizeString(payload.session_id, 128) || `${year}${month}${day}${hour}${minute}`;
  }
  return `${year}${month}${day}`;
}

function validateEventPayload(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error('invalid_payload');
  }

  for (const key of Object.keys(payload)) {
    if (!ALLOWED_PAYLOAD_KEYS.has(key)) {
      throw new Error(`unexpected_field:${key}`);
    }
  }

  const eventType = String(payload.event_type || '').trim();
  const channel = String(payload.channel || 'unknown').trim() || 'unknown';
  const briefingId = String(payload.briefing_id || '').trim();
  const itemId = payload.item_id == null ? undefined : String(payload.item_id).trim();
  const anonymousId = payload.anonymous_id == null ? undefined : String(payload.anonymous_id).trim();

  if (!ALLOWED_EVENT_TYPES.has(eventType)) {
    throw new Error('invalid_event_type');
  }
  if (!ALLOWED_CHANNELS.has(channel)) {
    throw new Error('invalid_channel');
  }
  if (!BRIEFING_ID_RE.test(briefingId)) {
    throw new Error('invalid_briefing_id');
  }
  if (itemId && !ITEM_ID_RE.test(itemId)) {
    throw new Error('invalid_item_id');
  }
  if (anonymousId && !ANON_ID_RE.test(anonymousId)) {
    throw new Error('invalid_anonymous_id');
  }

  const normalized = {
    event_type: eventType,
    channel,
    briefing_id: briefingId,
  };
  if (itemId) {
    normalized.item_id = itemId;
  }
  if (anonymousId) {
    normalized.anonymous_id = anonymousId;
  }

  if ((eventType === 'like' || eventType === 'dislike') && !itemId) {
    throw new Error('missing_item_id');
  }
  if (eventType === 'click') {
    if (!itemId) {
      throw new Error('missing_item_id');
    }
    normalized.target_url = normalizeTargetUrl(payload.target_url);
  } else if (payload.target_url != null) {
    normalized.target_url = normalizeTargetUrl(payload.target_url);
  }

  if (eventType === 'dwell') {
    normalized.duration_ms = normalizeDuration(payload.duration_ms);
    if (normalized.duration_ms == null) {
      throw new Error('missing_duration_ms');
    }
  } else if (payload.duration_ms != null) {
    normalized.duration_ms = normalizeDuration(payload.duration_ms);
  }

  const metadata = sanitizeMetadata(payload.metadata);
  if (metadata) {
    normalized.metadata = metadata;
  }

  normalized.time_bucket = deriveTimeBucket(normalized);
  normalized.idempotency_key = sanitizeString(payload.idempotency_key, 128) || deriveIdempotencyKey(normalized);
  normalized.id = `evt_${randomHex(16)}`;
  return normalized;
}

function createMemoryStore() {
  const events = [];
  const byIdempotency = new Map();
  return {
    insert(event) {
      if (byIdempotency.has(event.idempotency_key)) {
        return { duplicate: true, event: byIdempotency.get(event.idempotency_key) };
      }
      const stored = {
        ...event,
        created_at: new Date().toISOString(),
        metadata_json: event.metadata ? JSON.stringify(event.metadata) : null,
      };
      delete stored.metadata;
      byIdempotency.set(event.idempotency_key, stored);
      events.push(stored);
      return { duplicate: false, event: stored };
    },
    size() {
      return events.length;
    },
    all() {
      return events.slice();
    },
  };
}

function getStore(env) {
  if (!env.FEEDBACK_STORE) {
    env.FEEDBACK_STORE = createMemoryStore();
  }
  return env.FEEDBACK_STORE;
}

function hasD1Database(env) {
  return Boolean(env && env.DB && typeof env.DB.prepare === 'function');
}

function eventToDbParams(event) {
  return {
    id: event.id,
    event_type: event.event_type,
    channel: event.channel,
    anonymous_id: event.anonymous_id || null,
    briefing_id: event.briefing_id,
    item_id: event.item_id || null,
    target_url: event.target_url || null,
    duration_ms: event.duration_ms == null ? null : event.duration_ms,
    idempotency_key: event.idempotency_key,
    metadata_json: event.metadata ? JSON.stringify(event.metadata) : null,
  };
}

async function insertEvent(env, event) {
  if (!hasD1Database(env)) {
    return getStore(env).insert(event);
  }

  const params = eventToDbParams(event);
  try {
    await env.DB.prepare(`
      INSERT INTO feedback_events (
        id,
        event_type,
        channel,
        anonymous_id,
        briefing_id,
        item_id,
        target_url,
        duration_ms,
        idempotency_key,
        metadata_json
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `)
      .bind(
        params.id,
        params.event_type,
        params.channel,
        params.anonymous_id,
        params.briefing_id,
        params.item_id,
        params.target_url,
        params.duration_ms,
        params.idempotency_key,
        params.metadata_json,
      )
      .run();
    return { duplicate: false, event: params };
  } catch (error) {
    const message = String(error && error.message ? error.message : error);
    if (/unique|constraint/i.test(message)) {
      return { duplicate: true, event: null };
    }
    throw error;
  }
}

async function handleApiEvents(request, env) {
  const origin = request.headers.get('Origin');
  if (!isAllowedOrigin(origin, env)) {
    return jsonResponse({ ok: false, error: 'invalid_origin' }, 403);
  }
  const requestText = await request.text();
  if (requestText.length > 4096) {
    return jsonResponse({ ok: false, error: 'payload_too_large' }, 413, corsHeaders(origin, env));
  }

  let payload;
  try {
    payload = JSON.parse(requestText || '{}');
  } catch (_error) {
    return jsonResponse({ ok: false, error: 'invalid_json' }, 400, corsHeaders(origin, env));
  }

  try {
    const normalized = validateEventPayload(payload);
    const result = await insertEvent(env, normalized);
    return jsonResponse(
      {
        ok: true,
        event_id: result.duplicate ? null : result.event.id,
        duplicate: result.duplicate,
      },
      200,
      corsHeaders(origin, env),
    );
  } catch (error) {
    return jsonResponse({ ok: false, error: error.message || 'invalid_payload' }, 400, corsHeaders(origin, env));
  }
}

function thankYouHtml() {
  return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>反馈已记录</title><body><p>已记录，谢谢。</p></body></html>';
}

function unsafeRedirectHtml() {
  return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Unsafe redirect blocked</title><body><p>unsafe redirect blocked</p></body></html>';
}

async function handleRedirect(request, env) {
  const url = new URL(request.url);
  const target = url.searchParams.get('u');
  let safeTarget;
  try {
    safeTarget = normalizeTargetUrl(target);
  } catch (_error) {
    return htmlResponse(unsafeRedirectHtml(), 400);
  }

  try {
    const normalized = validateEventPayload({
      event_type: 'click',
      channel: url.searchParams.get('channel') || 'site',
      briefing_id: url.searchParams.get('briefing_id'),
      item_id: url.searchParams.get('item_id'),
      target_url: safeTarget,
      idempotency_key: url.searchParams.get('k') || undefined,
    });
    await insertEvent(env, normalized);
  } catch (_error) {
    // best effort only; never block safe reading redirects
  }

  return Response.redirect(safeTarget, 302);
}

async function handleFeedbackLink(request, env) {
  const url = new URL(request.url);
  if (!publicFallbackEnabled(env) && !isLocalFallbackHost(url.hostname)) {
    return htmlResponse(
      '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>feedback fallback disabled</title><body><p>local-only fallback disabled</p></body></html>',
      403,
    );
  }
  const action = url.searchParams.get('action');
  if (!['like', 'dislike'].includes(action)) {
    return htmlResponse('<!doctype html><html><body><p>invalid feedback action</p></body></html>', 400);
  }

  try {
    const normalized = validateEventPayload({
      event_type: action,
      channel: url.searchParams.get('channel') || 'site',
      briefing_id: url.searchParams.get('briefing_id'),
      item_id: url.searchParams.get('item_id'),
      anonymous_id: url.searchParams.get('anon'),
      metadata: {
        scope: 'item',
      },
    });
    await insertEvent(env, normalized);
  } catch (_error) {
    return htmlResponse('<!doctype html><html><body><p>invalid feedback request</p></body></html>', 400);
  }

  return htmlResponse(thankYouHtml(), 200);
}

async function handleRequest(request, env = {}) {
  const url = new URL(request.url);
  if (url.pathname === '/api/health' && request.method === 'GET') {
    return jsonResponse({
      ok: true,
      service: 'newsroom-feedback',
      version: env.FEEDBACK_VERSION || 'phase4-mvp',
      allowed_origins: parseAllowedOrigins(env),
    });
  }

  if (url.pathname === '/api/events' && !['OPTIONS', 'POST'].includes(request.method)) {
    return methodNotAllowed('OPTIONS, POST');
  }

  if (url.pathname === '/api/events' && request.method === 'OPTIONS') {
    const origin = request.headers.get('Origin');
    if (!isAllowedOrigin(origin, env)) {
      return jsonResponse({ ok: false, error: 'invalid_origin' }, 403);
    }
    return new Response(null, { status: 204, headers: corsHeaders(origin, env) });
  }

  if (url.pathname === '/api/events' && request.method === 'POST') {
    return handleApiEvents(request, env);
  }

  if (url.pathname === '/r' && request.method === 'GET') {
    return handleRedirect(request, env);
  }

  if (url.pathname === '/f' && request.method === 'GET') {
    return handleFeedbackLink(request, env);
  }

  return jsonResponse({ ok: false, error: 'not_found' }, 404);
}

if (typeof addEventListener === 'function') {
  addEventListener('fetch', (event) => {
    event.respondWith(handleRequest(event.request, globalThis));
  });
}

module.exports = {
  createMemoryStore,
  handleRequest,
  normalizeTargetUrl,
  hasD1Database,
  insertEvent,
  validateEventPayload,
};
