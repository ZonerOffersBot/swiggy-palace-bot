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

-- Ticket tier catalog; amounts are stored in INR paise and Stars units.
CREATE TABLE IF NOT EXISTS ticket_types (
  id BIGSERIAL PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL,
  price_inr BIGINT NOT NULL CHECK (price_inr > 0),
  price_stars BIGINT NOT NULL CHECK (price_stars > 0),
  position INTEGER NOT NULL DEFAULT 0,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS ticket_type_id BIGINT REFERENCES ticket_types(id);
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS ticket_type_id BIGINT REFERENCES ticket_types(id);
CREATE TABLE IF NOT EXISTS ticket_files (
  id BIGSERIAL PRIMARY KEY,
  ticket_type_id BIGINT NOT NULL REFERENCES ticket_types(id),
  file_type TEXT NOT NULL CHECK (file_type IN ('document','photo','text')),
  telegram_file_id TEXT,
  text_content TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  position INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO ticket_types(key,label,price_inr,price_stars,position,is_active)
VALUES ('general','General Ticket',49900,50,1,TRUE)
ON CONFLICT(key) DO NOTHING;


-- Additive compatibility fields for the extended admin panel. Existing rows are preserved.
ALTER TABLE orders ADD COLUMN IF NOT EXISTS gateway_order_id TEXT;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS ticket_type_id BIGINT REFERENCES ticket_types(id);
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS is_checked_in BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS checked_in_by BIGINT;
UPDATE tickets SET is_checked_in = (checked_in_at IS NOT NULL);
ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS replied_by BIGINT;
ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS replied_at TIMESTAMPTZ;
ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS message TEXT;
UPDATE support_tickets SET message = COALESCE(message, query, '') WHERE message IS NULL;
ALTER TABLE force_channels ADD COLUMN IF NOT EXISTS invite_link TEXT;
ALTER TABLE force_channels ADD COLUMN IF NOT EXISTS added_by BIGINT;
ALTER TABLE admins ADD COLUMN IF NOT EXISTS added_by BIGINT;
ALTER TABLE admins ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE ticket_files ADD COLUMN IF NOT EXISTS file_id TEXT;
ALTER TABLE ticket_files ADD COLUMN IF NOT EXISTS file_name TEXT;
ALTER TABLE ticket_files ADD COLUMN IF NOT EXISTS mime_type TEXT;
ALTER TABLE ticket_files ADD COLUMN IF NOT EXISTS file_size BIGINT;
ALTER TABLE ticket_files ADD COLUMN IF NOT EXISTS caption TEXT;
ALTER TABLE ticket_files ADD COLUMN IF NOT EXISTS added_by BIGINT;
UPDATE ticket_files SET file_id = COALESCE(file_id, telegram_file_id) WHERE file_id IS NULL;

-- Free-ticket promo codes, redeemed atomically with order creation.
ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_amount_check;
ALTER TABLE orders ADD CONSTRAINT orders_amount_nonnegative CHECK (amount >= 0);
ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_gateway_check;
ALTER TABLE orders ADD CONSTRAINT orders_gateway_allowed CHECK (gateway IN ('phonepe','stars','promo'));
CREATE TABLE IF NOT EXISTS promo_codes (
  code TEXT PRIMARY KEY,
  max_uses INTEGER,
  uses_count INTEGER NOT NULL DEFAULT 0 CHECK (uses_count >= 0),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_by BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (max_uses IS NULL OR max_uses > 0)
);
CREATE TABLE IF NOT EXISTS promo_redemptions (
  id BIGSERIAL PRIMARY KEY,
  code TEXT NOT NULL REFERENCES promo_codes(code),
  user_id BIGINT NOT NULL REFERENCES users(telegram_id),
  order_id UUID NOT NULL UNIQUE REFERENCES orders(order_id),
  redeemed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(code, user_id)
);
