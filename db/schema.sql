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

-- Small key/value store (tracks last visit-digest timestamp, etc.)
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_type    ON events (type);
CREATE INDEX IF NOT EXISTS idx_events_created ON events (created_at);
CREATE INDEX IF NOT EXISTS idx_signups_created ON signups (created_at);

-- Outreach CRM: internal call-tracking for the sales pipeline (passcode-gated, not public)
CREATE TABLE IF NOT EXISTS crm_contacts (
  id              SERIAL PRIMARY KEY,
  company         TEXT NOT NULL,
  phone           TEXT,
  email           TEXT,
  what_they_do    TEXT,
  contact_name    TEXT,           -- who to ask for (owner/founder/MD/director)
  contact_title   TEXT,
  confidence      TEXT,           -- High | Medium | Low | '' (how sure we are of contact_name)
  status          TEXT NOT NULL DEFAULT 'not_called',
  next_follow_up  DATE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS crm_calls (
  id          SERIAL PRIMARY KEY,
  contact_id  INTEGER NOT NULL REFERENCES crm_contacts(id) ON DELETE CASCADE,
  called_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  called_by   TEXT,
  response    TEXT,               -- e.g. No answer, Spoke with contact, Interested, Not interested...
  notes       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_crm_calls_contact ON crm_calls (contact_id);
CREATE INDEX IF NOT EXISTS idx_crm_calls_called_at ON crm_calls (called_at);
