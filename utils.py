import json
import logging
from aiogram import Bot
from config import ADMIN_IDS
from db import db
log = logging.getLogger(__name__)

async def is_admin(user_id: int) -> bool:
    if user_id in ADMIN_IDS: return True
    return bool(await db().fetchval("SELECT EXISTS(SELECT 1 FROM admins WHERE telegram_id=$1)", user_id))

async def notify_admins(bot: Bot, text: str):
    ids = set(ADMIN_IDS)
    try: ids.update(r["telegram_id"] for r in await db().fetch("SELECT telegram_id FROM admins"))
    except Exception: log.exception("Could not load database admins")
    for uid in ids:
        try: await bot.send_message(uid, text)
        except Exception: log.warning("Admin notification failed for %s", uid)

async def log_audit(user_id: int, action: str, details: dict | None = None):
    log.info("admin_action user=%s action=%s details=%s", user_id, action, json.dumps(details or {}, ensure_ascii=False, default=str))
