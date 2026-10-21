import time
import logging
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from db import db
from utils import is_admin

log = logging.getLogger(__name__)

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate: float = 0.7):
        self.rate = rate
        self.cache = {}

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)
        now = time.monotonic()
        if now - self.cache.get(user.id, 0) < self.rate:
            if isinstance(event, CallbackQuery):
                await event.answer("Thoda ruk kar dobara try karein.")
            return
        self.cache[user.id] = now
        return await handler(event, data)

class ForceJoinMiddleware(BaseMiddleware):
    EXEMPT = {"/start", "/help", "/cancel", "/admin"}

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user is None or await is_admin(user.id):
            return await handler(event, data)
        if isinstance(event, Message):
            text = (event.text or "").strip()
            command = text.split(maxsplit=1)[0].split("@", 1)[0] if text else ""
            if command in self.EXEMPT:
                return await handler(event, data)
        rows = await db().fetch("SELECT channel_id, channel_username, invite_link FROM force_channels WHERE is_active=TRUE")
        if not rows:
            return await handler(event, data)
        pending = []
        bot = data["bot"]
        for row in rows:
            try:
                member = await bot.get_chat_member(row["channel_id"], user.id)
                if member.status in ("left", "kicked") or (member.status == "restricted" and not getattr(member, "is_member", False)):
                    pending.append(row)
            except Exception:
                # Fail closed if the bot cannot verify membership.
                log.exception("Force-join membership check failed for %s", row["channel_id"])
                pending.append(row)
        if not pending:
            return await handler(event, data)
        kb = InlineKeyboardBuilder()
        for row in pending:
            username = (row["channel_username"] or "").lstrip("@")
            if username:
                kb.button(text=f"📢 Join @{username}", url=f"https://t.me/{username}")
            elif row["invite_link"]:
                kb.button(text="📢 Join required channel", url=row["invite_link"])
        kb.button(text="✅ I Joined — Verify", callback_data="forcejoin:verify")
        kb.adjust(1)
        text = "🔒 Bot use karne ke liye pehle required channel(s) join karein."
        if isinstance(event, Message):
            await event.answer(text, reply_markup=kb.as_markup())
        elif isinstance(event, CallbackQuery):
            await event.answer("Pehle required channel join karein.", show_alert=True)
            if event.message:
                await event.message.answer(text, reply_markup=kb.as_markup())
        return
