import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
if OWNER_ID:
    ADMIN_IDS.add(OWNER_ID)

DATABASE_PATH = os.getenv("DATABASE_PATH", "palace.db")
PORT = int(os.getenv("PORT", "10000") or 10000)
