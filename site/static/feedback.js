(function (globalScope) {
  const STORAGE_KEY = 'newsroom.feedback.anonymous_id';
  const CLIENT_VERSION = 'phase4-mvp';
  const ALLOWED_EVENT_TYPES = new Set(['like', 'dislike', 'click', 'dwell', 'read']);
  const ALLOWED_CHANNELS = new Set(['site', 'telegram', 'obsidian', 'manual', 'unknown']);
  const METADATA_KEYS = new Set(['source', 'tag', 'tags', 'scope', 'dwell_bucket', 'client_version']);
  const BRIEFING_ID_RE = /^\d{4}-\d{2}-\d{2}-(08|13|20|morning|noon|evening|monthly)$/;
  const ITEM_ID_RE = /^\d{4}-\d{2}-\d{2}-(08|13|20)-\d{3}$/;
  const ANONYMOUS_ID_RE = /^anon_[A-Za-z0-9._:-]{8,128}$/;

  function isObject(value) {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
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
    if (!isObject(metadata)) {
      return undefined;
    }

    const cleaned = {};
    for (const [key, value] of Object.entries(metadata)) {
      if (!METADATA_KEYS.has(key)) {
        continue;
      }
      if (key === 'tags') {
        if (!Array.isArray(value)) {
          continue;
        }
        const tags = value
          .map((entry) => sanitizeString(entry, 50))
          .filter(Boolean)
          .slice(0, 5);
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
      throw new Error('metadata exceeds 1024 bytes');
    }
    return cleaned;
  }

  function ensureEventType(eventType) {
    if (!ALLOWED_EVENT_TYPES.has(eventType)) {
      throw new Error('event_type is invalid');
    }
  }

  function ensureChannel(channel) {
    if (!ALLOWED_CHANNELS.has(channel)) {
      throw new Error('channel is invalid');
    }
  }

  function ensureBriefingId(briefingId) {
    if (!BRIEFING_ID_RE.test(String(briefingId || ''))) {
      throw new Error('briefing_id is invalid');
    }
  }

  function ensureItemId(itemId) {
    if (itemId == null || itemId === '') {
      return;
    }
    if (!ITEM_ID_RE.test(String(itemId))) {
      throw new Error('item_id is invalid');
    }
  }

  function ensureAnonymousId(anonymousId) {
    if (anonymousId == null || anonymousId === '') {
      return;
    }
    if (!ANONYMOUS_ID_RE.test(String(anonymousId))) {
      throw new Error('anonymous_id is invalid');
    }
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
    return /^(localhost|127\.0\.0\.1)$/i.test(normalized)
      || normalized === '::1'
      || normalized === '0:0:0:0:0:0:0:1';
  }

  function ensureTargetUrl(targetUrl) {
    if (typeof targetUrl !== 'string' || !targetUrl.trim()) {
      throw new Error('target_url is required');
    }
    const parsed = new URL(targetUrl);
    if (parsed.protocol === 'https:') {
      if (isPrivateOrLoopbackHost(parsed.hostname)) {
        throw new Error('target_url must not use a private IP host');
      }
      return parsed.toString();
    }
    if (parsed.protocol === 'http:' && isLocalDevHost(parsed.hostname)) {
      return parsed.toString();
    }
    throw new Error('target_url must use https or localhost http');
  }

  function normalizeDuration(durationMs) {
    if (durationMs == null) {
      return undefined;
    }
    if (!Number.isFinite(durationMs)) {
      throw new Error('duration_ms is invalid');
    }
    const rounded = Math.max(0, Math.min(Math.round(durationMs), 30 * 60 * 1000));
    return rounded;
  }

  function buildEventPayload(options) {
    const eventType = String(options.eventType || '').trim();
    const channel = String(options.channel || 'unknown').trim() || 'unknown';
    const briefingId = options.briefingId;
    const itemId = options.itemId;
    const anonymousId = options.anonymousId;
    const metadata = sanitizeMetadata(options.metadata);

    ensureEventType(eventType);
    ensureChannel(channel);
    ensureBriefingId(briefingId);
    ensureItemId(itemId);
    ensureAnonymousId(anonymousId);

    const payload = {
      event_type: eventType,
      channel,
      briefing_id: String(briefingId),
    };

    if (itemId) {
      payload.item_id = String(itemId);
    }
    if (anonymousId) {
      payload.anonymous_id = String(anonymousId);
    }

    if (eventType === 'like' || eventType === 'dislike') {
      if (!itemId) {
        throw new Error('like and dislike events require item_id');
      }
    }

    if (eventType === 'click') {
      payload.target_url = ensureTargetUrl(options.targetUrl);
      if (!payload.item_id) {
        throw new Error('click events require item_id');
      }
    } else if (options.targetUrl) {
      payload.target_url = ensureTargetUrl(options.targetUrl);
    }

    if (eventType === 'dwell') {
      const duration = normalizeDuration(options.durationMs);
      if (duration == null) {
        throw new Error('dwell events require duration_ms');
      }
      payload.duration_ms = duration;
    } else if (options.durationMs != null) {
      payload.duration_ms = normalizeDuration(options.durationMs);
    }

    if (options.idempotencyKey) {
      payload.idempotency_key = String(options.idempotencyKey);
    }
    if (metadata) {
      payload.metadata = metadata;
    }
    return payload;
  }

  function normalizeBaseUrl(baseUrl) {
    return String(baseUrl || '').trim().replace(/\/+$/, '');
  }

  function buildTrackingUrl(workerBaseUrl, options) {
    const baseUrl = normalizeBaseUrl(workerBaseUrl);
    if (!baseUrl) {
      throw new Error('worker_base_url is required');
    }
    const payload = buildEventPayload({
      eventType: 'click',
      channel: options.channel || 'site',
      briefingId: options.briefingId,
      itemId: options.itemId,
      anonymousId: options.anonymousId,
      targetUrl: options.targetUrl,
      idempotencyKey: options.idempotencyKey,
    });
    const params = new URLSearchParams({
      u: payload.target_url,
      briefing_id: payload.briefing_id,
    });
    if (payload.item_id) {
      params.set('item_id', payload.item_id);
    }
    params.set('channel', payload.channel);
    return `${baseUrl}/r?${params.toString()}`;
  }

  function bucketDwellDuration(durationMs) {
    if (durationMs < 10_000) {
      return '0-10s';
    }
    if (durationMs < 30_000) {
      return '10-30s';
    }
    if (durationMs < 120_000) {
      return '30-120s';
    }
    return '120s+';
  }

  function safeParseJson(text) {
    try {
      return JSON.parse(text);
    } catch (_error) {
      return null;
    }
  }

  function readJsonScript(documentRef, id) {
    const node = documentRef.getElementById(id);
    if (!node) {
      return null;
    }
    return safeParseJson(node.textContent || 'null');
  }

  function createAnonymousId() {
    if (globalScope.crypto && typeof globalScope.crypto.randomUUID === 'function') {
      return `anon_${globalScope.crypto.randomUUID()}`;
    }
    return `anon_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
  }

  function getOrCreateAnonymousId(storage) {
    if (!storage) {
      return createAnonymousId();
    }
    const existing = storage.getItem(STORAGE_KEY);
    if (existing && ANONYMOUS_ID_RE.test(existing)) {
      return existing;
    }
    const created = createAnonymousId();
    storage.setItem(STORAGE_KEY, created);
    return created;
  }

  function setStatus(statusRoot, message, isError) {
    const node = statusRoot.querySelector('[data-feedback-status]');
    if (!node) {
      return;
    }
    node.textContent = message;
    node.dataset.state = isError ? 'error' : 'ok';
  }

  async function postEvent(config, payload) {
    const response = await globalScope.fetch(`${normalizeBaseUrl(config.workerBaseUrl)}/api/events`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
      keepalive: true,
    });
    const text = await response.text();
    const parsed = safeParseJson(text) || { ok: false, error: text || 'unknown_error' };
    if (!response.ok || !parsed.ok) {
      throw new Error(parsed.error || `request failed with ${response.status}`);
    }
    return parsed;
  }

  function maybeSendBeacon(config, payload) {
    if (globalScope.navigator && typeof globalScope.navigator.sendBeacon === 'function') {
      const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
      return globalScope.navigator.sendBeacon(`${normalizeBaseUrl(config.workerBaseUrl)}/api/events`, blob);
    }
    postEvent(config, payload).catch(function () {
      return null;
    });
    return false;
  }

  function metadataForItem(container) {
    const metadata = {
      scope: 'item',
      client_version: CLIENT_VERSION,
    };
    if (container.dataset.feedbackSource) {
      metadata.source = container.dataset.feedbackSource;
    }
    if (container.dataset.feedbackTags) {
      const tags = container.dataset.feedbackTags
        .split(',')
        .map((tag) => tag.trim())
        .filter(Boolean)
        .slice(0, 5);
      if (tags.length) {
        metadata.tags = tags;
      }
    }
    return metadata;
  }

  function attachFeedbackButtons(documentRef, config, anonymousId) {
    const containers = documentRef.querySelectorAll('[data-feedback-item]');
    if (!containers.length) {
      return;
    }
    containers.forEach((container) => {
      const buttons = container.querySelectorAll('[data-feedback-action]');
      buttons.forEach((button) => {
        button.addEventListener('click', async function () {
          try {
            const payload = buildEventPayload({
              eventType: button.dataset.feedbackAction,
              channel: config.channel || 'site',
              briefingId: container.dataset.feedbackBriefingId,
              itemId: container.dataset.feedbackItemId,
              anonymousId,
              metadata: metadataForItem(container),
            });
            const result = await postEvent(config, payload);
            setStatus(container, result.duplicate ? '这条反馈已记录（重复提交已忽略）。' : '已记录这条新闻的反馈，谢谢。', false);
          } catch (_error) {
            setStatus(container, '暂时无法记录这条反馈，但不影响阅读。', true);
          }
        });
      });
    });
  }

  function rewriteTrackedLinks(documentRef, config, items, anonymousId) {
    if (!Array.isArray(items) || !items.length) {
      return;
    }
    const itemByUrl = new Map();
    items.forEach((item) => {
      if (item && item.url) {
        itemByUrl.set(item.url, item);
      }
    });

    const anchors = documentRef.querySelectorAll('article section a[href]');
    anchors.forEach((anchor) => {
      const originalHref = anchor.getAttribute('href');
      if (!originalHref || !/^https?:\/\//i.test(originalHref)) {
        return;
      }
      const item = itemByUrl.get(originalHref);
      if (!item) {
        return;
      }
      anchor.dataset.feedbackItemId = item.item_id || '';
      anchor.dataset.feedbackBriefingId = item.briefing_id || config.primaryBriefingId || '';
      anchor.dataset.feedbackOriginalUrl = originalHref;
      anchor.rel = 'noopener noreferrer';
      anchor.href = buildTrackingUrl(config.workerBaseUrl, {
        targetUrl: originalHref,
        briefingId: item.briefing_id || config.primaryBriefingId,
        itemId: item.item_id,
        channel: config.channel || 'site',
      });
    });
  }

  function setupDwellTracking(documentRef, config, anonymousId) {
    let visibleSince = documentRef.visibilityState === 'hidden' ? 0 : Date.now();
    let accumulated = 0;
    let sent = false;

    function stopTimer() {
      if (!visibleSince) {
        return;
      }
      accumulated += Date.now() - visibleSince;
      visibleSince = 0;
    }

    function startTimer() {
      if (!visibleSince) {
        visibleSince = Date.now();
      }
    }

    function flush() {
      if (sent) {
        return;
      }
      stopTimer();
      const durationMs = Math.max(0, accumulated);
      if (!durationMs) {
        return;
      }
      sent = true;
      try {
        const payload = buildEventPayload({
          eventType: 'dwell',
          channel: config.channel || 'site',
          briefingId: config.primaryBriefingId,
          anonymousId,
          durationMs,
          metadata: {
            scope: 'briefing',
            dwell_bucket: bucketDwellDuration(durationMs),
            client_version: CLIENT_VERSION,
          },
        });
        maybeSendBeacon(config, payload);
      } catch (_error) {
        sent = true;
      }
    }

    documentRef.addEventListener('visibilitychange', function () {
      if (documentRef.visibilityState === 'hidden') {
        stopTimer();
      } else {
        startTimer();
      }
    });
    globalScope.addEventListener('pagehide', flush);
  }

  function initFeedback(documentRef) {
    const doc = documentRef || globalScope.document;
    if (!doc) {
      return;
    }
    const config = readJsonScript(doc, 'newsroom-feedback-config');
    if (!isObject(config) || !config.enabled || !config.workerBaseUrl || !config.primaryBriefingId) {
      return;
    }
    const items = readJsonScript(doc, 'newsroom-feedback-items') || [];
    const anonymousId = getOrCreateAnonymousId(globalScope.localStorage);

    if (config.trackLinks) {
      rewriteTrackedLinks(doc, config, items, anonymousId);
    }
    if (config.widgetEnabled) {
      attachFeedbackButtons(doc, config, anonymousId);
    }
    if (config.dwellEnabled) {
      setupDwellTracking(doc, config, anonymousId);
    }
  }

  const exported = {
    buildEventPayload,
    buildTrackingUrl,
    bucketDwellDuration,
    getOrCreateAnonymousId,
    initFeedback,
    sanitizeMetadata,
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = exported;
  }

  if (globalScope && globalScope.document) {
    if (globalScope.document.readyState === 'loading') {
      globalScope.document.addEventListener('DOMContentLoaded', function () {
        initFeedback(globalScope.document);
      });
    } else {
      initFeedback(globalScope.document);
    }
  }
})(typeof globalThis !== 'undefined' ? globalThis : window);
