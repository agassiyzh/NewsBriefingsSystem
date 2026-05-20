PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS feedback_events (
  id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL CHECK (event_type IN ('like', 'dislike', 'click', 'dwell', 'read')),
  channel TEXT NOT NULL CHECK (channel IN ('site', 'telegram', 'obsidian', 'manual', 'unknown')),
  anonymous_id TEXT,
  briefing_id TEXT NOT NULL,
  item_id TEXT,
  target_url TEXT,
  duration_ms INTEGER,
  idempotency_key TEXT NOT NULL UNIQUE,
  metadata_json TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_feedback_events_created_at
ON feedback_events (created_at);

CREATE INDEX IF NOT EXISTS idx_feedback_events_briefing_item
ON feedback_events (briefing_id, item_id);

CREATE INDEX IF NOT EXISTS idx_feedback_events_type_channel
ON feedback_events (event_type, channel);
