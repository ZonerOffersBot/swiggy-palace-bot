CREATE TABLE IF NOT EXISTS users (
  telegram_id BIGINT PRIMARY KEY,
  username TEXT,
  first_name TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS orders (
  order_id UUID PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(telegram_id),
  amount BIGINT NOT NULL CHECK (amount > 0),
  currency TEXT NOT NULL CHECK (currency IN ('INR','XTR')),
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processing','paid','failed','cancelled','refunded')),
  gateway TEXT NOT NULL CHECK (gateway IN ('phonepe','stars')),
  gateway_txn_id TEXT UNIQUE,
  idempotency_key TEXT NOT NULL UNIQUE,
  gateway_order_id TEXT UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS tickets (
  ticket_id UUID PRIMARY KEY,
  order_id UUID NOT NULL UNIQUE REFERENCES orders(order_id),
  user_id BIGINT NOT NULL REFERENCES users(telegram_id),
  ticket_code TEXT NOT NULL UNIQUE,
  pdf_file_id TEXT,
  delivered_at TIMESTAMPTZ,
  checked_in_at TIMESTAMPTZ,
  checked_in_by BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS webhook_events (
  event_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS support_tickets (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(telegram_id),
  message TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  admin_reply TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS force_channels (
  id BIGSERIAL PRIMARY KEY,
  channel_id BIGINT NOT NULL UNIQUE,
  channel_username TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS admins (
  telegram_id BIGINT PRIMARY KEY,
  added_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS bot_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Delivery lease prevents duplicate sends when multiple workers reconcile the same order.
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS delivery_started_at TIMESTAMPTZ;
-- Payment reconciliation timestamps (safe additive migration).
ALTER TABLE orders ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ;

-- User-menu and support workflow additions (additive, preserves existing records).
ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name TEXT;
UPDATE users SET full_name = COALESCE(full_name, first_name, '') WHERE full_name IS NULL;
ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS username TEXT;
ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS full_name TEXT;
ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS query TEXT;
UPDATE support_tickets SET query = COALESCE(query, message, '') WHERE query IS NULL;
CREATE TABLE IF NOT EXISTS user_menu (
  key TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  is_active BOOLEAN NOT NULL DEFAULT TRUE
);
INSERT INTO user_menu(key,label,position,is_active) VALUES
 ('buy','🎟️ Book Ticket',1,TRUE),
 ('myticket','🎫 My Tickets',2,TRUE),
 ('help','🆘 Help / Support',3,TRUE)
ON CONFLICT(key) DO NOTHING;
