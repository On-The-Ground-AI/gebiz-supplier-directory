-- GeBIZ Supplier Directory — analytics + mailing list schema

-- Mailing list: one row per unique email
CREATE TABLE IF NOT EXISTS signups (
  id          SERIAL PRIMARY KEY,
  email       TEXT NOT NULL UNIQUE,
  name        TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  user_agent  TEXT,
  referrer    TEXT
);

-- Event log: visits and downloads
CREATE TABLE IF NOT EXISTS events (
  id          SERIAL PRIMARY KEY,
  type        TEXT NOT NULL,          -- 'visit' | 'download'
  email       TEXT,                   -- present for downloads (who downloaded)
  detail      JSONB,                  -- download: {epu:[], grades:[], years:[], search, activity, rows}
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  user_agent  TEXT,
  referrer    TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_type    ON events (type);
CREATE INDEX IF NOT EXISTS idx_events_created ON events (created_at);
CREATE INDEX IF NOT EXISTS idx_signups_created ON signups (created_at);
