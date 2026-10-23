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
        verification_errors = []
        for row in rows:
            member = None
            # Prefer the numeric channel ID, but fall back to the saved @username
            # in case an old/mistyped channel ID is stored in the admin panel.
            candidates = [row["channel_id"]]
            username = (row["channel_username"] or "").strip()
            if username:
                username = username.lstrip("@")
                candidates.append("@" + username)
            for chat_ref in candidates:
                try:
                    member = await bot.get_chat_member(chat_ref, user.id)
                    break
                except Exception as exc:
                    verification_errors.append((row, chat_ref, exc))
                    log.warning(
                        "Force-join lookup failed for channel_ref=%s user_id=%s: %s",
                        chat_ref, user.id, exc
                    )
            if member is None:
                # Never silently let users bypass a required channel, but make
                # the failure diagnosable instead of falsely claiming they did not join.
                pending.append(row)
                continue
            if member.status in ("left", "kicked") or (
                member.status == "restricted" and not getattr(member, "is_member", False)
            ):
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
        has_verification_error = any(
            row["channel_id"] == failed_row["channel_id"]
            for failed_row, _, _ in verification_errors
            for row in pending
        )
        text = "🔒 Bot use karne ke liye pehle required channel(s) join karein."
        if has_verification_error:
            text += (
                "\n\n⚠️ Channel membership verify nahi ho pa rahi. "
                "Bot ko channel mein admin banayein aur Admin Panel mein saved "
                "channel ID / @username check karein, phir Verify dabayein."
            )
        if isinstance(event, Message):
            await event.answer(text, reply_markup=kb.as_markup())
        elif isinstance(event, CallbackQuery):
            await event.answer("Pehle required channel join karein.", show_alert=True)
            if event.message:
                await event.message.answer(text, reply_markup=kb.as_markup())
        return


class BlacklistMiddleware(BaseMiddleware):
    """Block blacklisted non-admin users before any message or callback handler."""
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user is None or await is_admin(user.id):
            return await handler(event, data)
        try:
            blocked = await db().fetchval(
                "SELECT EXISTS(SELECT 1 FROM user_blacklist WHERE user_id=$1)",
                user.id,
            )
        except Exception:
            log.exception("Blacklist lookup failed for user %s", user.id)
            # Fail closed for ordinary users if blacklist status cannot be verified.
            if isinstance(event, Message):
                await event.answer("⚠️ User access verify nahi ho pa raha. Thodi der baad try karein.")
            elif isinstance(event, CallbackQuery):
                await event.answer("User access verify nahi ho pa raha. Baad mein try karein.", show_alert=True)
            return
        if not blocked:
            return await handler(event, data)
        if isinstance(event, Message):
            await event.answer("🚫 Aapka bot access Main Admin ne block kiya hai. Agar ye galti hai, admin se contact karein.")
        elif isinstance(event, CallbackQuery):
            await event.answer("🚫 Aapka bot access block hai.", show_alert=True)
        return
