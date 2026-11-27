import os
from dotenv import load_dotenv
load_dotenv()

def env_int(name, default):
    try: return int(os.getenv(name, str(default)))
    except (TypeError, ValueError): return default

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
# Set MAIN_ADMIN_ID in Render to the owner Telegram ID. If omitted, the first ADMIN_IDS value is used.
MAIN_ADMIN_ID = int(os.getenv("MAIN_ADMIN_ID", next((x.strip() for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()), "0")))
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
PHONEPE_CLIENT_ID = os.getenv("PHONEPE_CLIENT_ID", "").strip()
PHONEPE_CLIENT_SECRET = os.getenv("PHONEPE_CLIENT_SECRET", "").strip()
PHONEPE_CLIENT_VERSION = os.getenv("PHONEPE_CLIENT_VERSION", "1").strip()
PHONEPE_ENV = os.getenv("PHONEPE_ENV", "SANDBOX").upper()
PHONEPE_MERCHANT_ID = os.getenv("PHONEPE_MERCHANT_ID", "").strip()
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "").rstrip("/")
EVENT_NAME = os.getenv("EVENT_NAME", "Live Show")
EVENT_DATE = os.getenv("EVENT_DATE", "Date to be announced")
VENUE = os.getenv("VENUE", "Venue to be announced")
TICKET_PRICE_INR = env_int("TICKET_PRICE_INR", 499)
TICKET_PRICE_STARS = env_int("TICKET_PRICE_STARS", 50)
PORT = env_int("PORT", 8080)

def validate_config():
    if not BOT_TOKEN or ":" not in BOT_TOKEN:
        raise RuntimeError("Set a valid BOT_TOKEN in environment variables.")
    if not DATABASE_URL.startswith(("postgres://", "postgresql://")):
        raise RuntimeError("DATABASE_URL must be a PostgreSQL connection URL.")
    if TICKET_PRICE_INR <= 0 or TICKET_PRICE_STARS <= 0:
        raise RuntimeError("Ticket prices must be positive.")
