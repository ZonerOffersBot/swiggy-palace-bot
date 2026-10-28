import json
import logging
from aiogram import Bot
from config import ADMIN_IDS, MAIN_ADMIN_ID
from db import db
log = logging.getLogger(__name__)

async def is_admin(user_id: int) -> bool:
    if user_id in ADMIN_IDS or (MAIN_ADMIN_ID and user_id == MAIN_ADMIN_ID): return True
    return bool(await db().fetchval("SELECT EXISTS(SELECT 1 FROM admins WHERE telegram_id=$1 AND COALESCE(is_active, TRUE)=TRUE)", user_id))

async def notify_admins(bot: Bot, text: str):
    ids = set(ADMIN_IDS)
    if MAIN_ADMIN_ID:
        ids.add(MAIN_ADMIN_ID)
    try: ids.update(r["telegram_id"] for r in await db().fetch("SELECT telegram_id FROM admins WHERE COALESCE(is_active, TRUE)=TRUE"))
    except Exception: log.exception("Could not load database admins")
    for uid in ids:
        try: await bot.send_message(uid, text)
        except Exception: log.warning("Admin notification failed for %s", uid)

async def log_audit(user_id: int, action: str, details: dict | None = None):
    log.info("admin_action user=%s action=%s details=%s", user_id, action, json.dumps(details or {}, ensure_ascii=False, default=str))


async def get_setting(key: str, default: str = "") -> str:
    try:
        value = await db().fetchval("SELECT value FROM bot_settings WHERE key=$1", key)
        return default if value is None else str(value)
    except Exception:
        log.exception("Could not read setting %s", key)
        return default


async def get_all_admin_ids() -> set[int]:
    ids = set(ADMIN_IDS)
    if MAIN_ADMIN_ID:
        ids.add(MAIN_ADMIN_ID)
    try:
        ids.update(int(r["telegram_id"]) for r in await db().fetch("SELECT telegram_id FROM admins WHERE COALESCE(is_active, TRUE)=TRUE"))
    except Exception:
        log.exception("Could not load admin IDs")
    return ids


async def set_setting(key: str, value: str) -> None:
    await db().execute(
        """INSERT INTO bot_settings(key, value, updated_at) VALUES($1, $2, NOW())
           ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()""",
        key, value,
    )


# Compatibility aliases for admin handlers from the expanded ticket workflow.
async def IsAdmin(user_id: int) -> bool:
    return await is_admin(user_id)
