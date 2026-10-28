import asyncio
import logging
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from config import EVENT_NAME
from db import db
from utils import is_admin, log_audit
log = logging.getLogger(__name__)
router=Router()

def admin_keyboard():
    kb = InlineKeyboardBuilder()
    buttons = [
        ("📊 Stats", "admin:stats"), ("🎟 Ticket Types", "admin:tiers"),
        ("🎁 Promo Codes", "admin:promos"),
        ("📁 Ticket Files", "admin:files"), ("💰 Wallet", "admin:wallet_home"),
        ("🛒 JSON Shop Files", "admin:wallet_inventory"), ("🧾 Transaction History", "admin:wallet_history"), ("⚙️ Settings", "admin:settings"),
        ("🧭 User Menu", "admin:menu"), ("📢 Force Join", "admin:force"),
        ("👥 User & Wallet Control", "admin:users"), ("👮 Admins", "admin:admins"), ("🆘 Support", "admin:support"),\n        ("📣 Broadcast", "admin:broadcast"),
        ("🔄 Refresh", "admin:home"),
    ]
    for label, data in buttons:
        kb.button(text=label, callback_data=data)
    kb.adjust(2, 2, 2, 2, 2, 2)
    return kb.as_markup()


async def admin_home_text():
    users = await db().fetchval("SELECT COUNT(*) FROM users")
    orders = await db().fetchval("SELECT COUNT(*) FROM orders")
    paid = await db().fetchval("SELECT COUNT(*) FROM orders WHERE status='paid'")
    tickets = await db().fetchval("SELECT COUNT(*) FROM tickets")
    return (f"🛠️ <b>{EVENT_NAME} Admin Panel</b>\n\n"
            f"👥 Users: {users}\n🧾 Orders: {orders}\n"
            f"✅ Paid orders: {paid}\n🎟 Tickets issued: {tickets}\n\n"
            "Neeche kisi section ko select karein.")


@router.message(Command("admin"))
async def admin_panel(msg: Message):
    if not await is_admin(msg.from_user.id):
        await msg.answer(
            "⛔ Admin access nahi hai.\n"
            f"Aapki Telegram ID: <code>{msg.from_user.id}</code>\n\n"
            "Render → Environment mein ADMIN_IDS ke andar ye ID add karein "
            "(multiple admins ke liye comma-separated IDs), phir service redeploy/restart karein."
        )
        return
    try:
        await msg.answer(await admin_home_text(), reply_markup=admin_keyboard())
    except Exception:
        log.exception("Admin panel failed for user %s", msg.from_user.id)
        await msg.answer("⚠️ Admin panel database error. Render Logs mein /admin ke baad wali traceback check karein.")


@router.callback_query(F.data.in_({"admin:home", "admin:stats", "admin:tiers", "admin:files", "admin:settings", "admin:menu", "admin:force", "admin:admins", "admin:support", "admin:promos"}))
async def admin_navigation(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    section = cb.data.split(":", 1)[1]
    section_markup = admin_keyboard()
    try:
        if section in ("home", "stats"):
            text = await admin_home_text()
        elif section == "tiers":
            rows = await db().fetch("SELECT id,label,price_inr,price_stars,is_active FROM ticket_types ORDER BY position,id")
            text = "🎟 <b>Ticket Types</b>\n" + ("\n".join(f"• {r['label']} — ₹{r['price_inr']/100:.2f} / ⭐ {r['price_stars']} — {'Active' if r['is_active'] else 'Inactive'} (ID {r['id']})" for r in rows) or "Abhi koi ticket type nahi hai.")
            kb = InlineKeyboardBuilder()
            for r in rows:
                kb.button(text=f"✏️ Edit {r['label'][:24]}", callback_data=f"admin:edit_tier:{r['id']}")
                kb.button(text=f"📎 Add file: {r['label'][:18]}", callback_data=f"admin:add_file:{r['id']}")
            kb.button(text="⬅️ Admin home", callback_data="admin:home")
            kb.adjust(1)
            section_markup = kb.as_markup()
        elif section == "promos":
            rows = await db().fetch("SELECT code,max_uses,uses_count,is_active,created_at FROM promo_codes ORDER BY created_at DESC LIMIT 30")
            text = "🎁 <b>Free Ticket Promo Codes</b>\nCode use karne par eligible user ko free ticket milega.\n" + ("\n".join(f"• <code>{r['code']}</code> — {r['uses_count']}/{r['max_uses'] if r['max_uses'] is not None else '∞'} used — {'Active' if r['is_active'] else 'Disabled'}" for r in rows) or "Abhi promo code nahi bana.")
            kb = InlineKeyboardBuilder()
            kb.button(text="➕ Create promo code", callback_data="admin:add_promo")
            for r in rows:
                action = "disable" if r["is_active"] else "enable"
                kb.button(text=f"{'⏸ Disable' if r['is_active'] else '▶️ Enable'} {r['code'][:20]}", callback_data=f"admin:{action}_promo:{r['code']}")
                kb.button(text=f"♻️ Reactivate {r['code'][:18]}", callback_data=f"admin:reactivate_promo:{r['code']}")
                kb.button(text=f"🗑 Delete {r['code'][:18]}", callback_data=f"admin:delete_promo:{r['code']}")
            kb.button(text="⬅️ Admin home", callback_data="admin:home")
            kb.adjust(1)
            section_markup = kb.as_markup()
        elif section == "files":
            rows = await db().fetch("SELECT f.id,t.label,f.file_type,f.is_active FROM ticket_files f JOIN ticket_types t ON t.id=f.ticket_type_id ORDER BY f.position DESC,f.id DESC LIMIT 30")
            text = "📁 <b>Ticket Files (latest 30)</b>\nHar file ke neeche Delete button hai. Delete karne se pehle confirmation maangi jayegi.\n\n" + ("\n".join(f"• #{r['id']} — {r['label']} — {r['file_type']} — {'Active' if r['is_active'] else 'Inactive'}" for r in rows) or "Abhi koi ticket file add nahi hai.")
            kb = InlineKeyboardBuilder()
            for r in rows:
                kb.button(text=f"🗑 Delete file #{r['id']}", callback_data=f"admin:delete_file_confirm:{r['id']}")
            tiers = await db().fetch("SELECT id,label FROM ticket_types ORDER BY position,id")
            for r in tiers:
                kb.button(text=f"➕ Add file: {r['label'][:28]}", callback_data=f"admin:add_file:{r['id']}")
            kb.button(text="🛒 JSON Shop Files", callback_data="admin:wallet_inventory")
            kb.button(text="⬅️ Admin home", callback_data="admin:home")
            kb.adjust(1)
            section_markup = kb.as_markup()
        elif section == "settings":
            rows = await db().fetch("SELECT key,value FROM bot_settings ORDER BY key")
            text = "⚙️ <b>Settings</b>\n" + ("\n".join(f"• <code>{r['key']}</code>: {r['value'][:150]}" for r in rows) or "Custom settings abhi set nahi hain.") + "\nEvent details yahin se edit kar sakte hain."
            kb = InlineKeyboardBuilder()
            for key, label in (("event_name","Event name"),("event_date","Event date"),("venue","Venue"),("welcome_msg","Welcome message")):
                kb.button(text=f"✏️ {label}", callback_data=f"admin:edit_setting:{key}")
            kb.button(text="⬅️ Admin home", callback_data="admin:home")
            kb.adjust(2,2,1)
            section_markup = kb.as_markup()
        elif section == "menu":
            rows = await db().fetch("SELECT key,label,is_active,position FROM user_menu ORDER BY position,key")
            text = "🧭 <b>User Menu</b>\nButton ka naam badalne ke liye Rename, aur dikhana/chhupana badalne ke liye Show/Hide dabayein. Button ka action fixed rahega.\n\n" + ("\n".join(f"• {r['position']}. {r['label']} — <code>{r['key']}</code> — {'Visible' if r['is_active'] else 'Hidden'}" for r in rows) or "User menu empty hai.")
            kb = InlineKeyboardBuilder()
            for r in rows:
                kb.button(text=f"✏️ Rename: {r['label'][:20]}", callback_data=f"admin:edit_menu:{r['key']}")
                kb.button(text=f"⬆️ {r['position']}", callback_data=f"admin:menu_move_up:{r['key']}")
                kb.button(text=f"⬇️ {r['position']}", callback_data=f"admin:menu_move_down:{r['key']}")
                action = "disable" if r["is_active"] else "enable"
                label = "🙈 Hide" if r["is_active"] else "👁 Show"
                kb.button(text=label, callback_data=f"admin:{action}_menu:{r['key']}")
            kb.button(text="⬅️ Admin home", callback_data="admin:home")
            kb.adjust(2, 2, 2, 1)
            section_markup = kb.as_markup()
        elif section == "force":
            rows = await db().fetch("SELECT channel_id,channel_username,invite_link,is_active FROM force_channels ORDER BY id")
            text = "📢 <b>Force Join Channels</b>\n" + ("\n".join(f"• {r['channel_username'] or r['channel_id']} — {'Active' if r['is_active'] else 'Inactive'}" for r in rows) or "Koi force-join channel configured nahi hai.")
            kb = InlineKeyboardBuilder()
            kb.button(text="➕ Add channel", callback_data="admin:add_force")
            for r in rows:
                action = "disable" if r['is_active'] else "enable"
                label = "⏸ Disable" if r['is_active'] else "▶️ Enable"
                kb.button(text=f"{label} {str(r['channel_username'] or r['channel_id'])[:24]}", callback_data=f"admin:{action}_force:{r['channel_id']}")
            kb.button(text="⬅️ Admin home", callback_data="admin:home")
            kb.adjust(1)
            section_markup = kb.as_markup()
        elif section == "admins":
            rows = await db().fetch("SELECT telegram_id,is_active FROM admins ORDER BY telegram_id")
            text = "👮 <b>Database Admins</b>\n" + ("\n".join(f"• <code>{r['telegram_id']}</code> — {'Active' if r['is_active'] else 'Inactive'}" for r in rows) or "Database admins list empty hai. Render ADMIN_IDS admins ko bhi access deta hai.")
            kb = InlineKeyboardBuilder()
            kb.button(text="➕ Add admin", callback_data="admin:add_admin")
            kb.button(text="➖ Remove admin", callback_data="admin:remove_admin")
            kb.button(text="⬅️ Admin home", callback_data="admin:home")
            kb.adjust(2,1)
            section_markup = kb.as_markup()
        elif section == "support":
            rows = await db().fetch(
                "SELECT id,user_id,COALESCE(full_name,'') AS full_name,COALESCE(query,message,'') AS query,status,created_at FROM support_tickets ORDER BY (status='open') DESC,created_at DESC LIMIT 20"
            )
            text = "🆘 <b>Recent Support Tickets</b>\nOpen ticket select karke conversation dekhein aur reply karein.\n"
            kb = InlineKeyboardBuilder()
            for r in rows:
                text += f"\n#{r['id']} — {r['full_name'] or r['user_id']} — {r['status']}\n{r['query'][:120]}\n"
                kb.button(text=f"📂 Open #{r['id']} ({r['status']})", callback_data=f"sup:view:{r['id']}")
            if not rows:
                text += "\nAbhi support tickets nahi hain."
            kb.button(text="⬅️ Admin home", callback_data="admin:home")
            kb.adjust(1)
            section_markup = kb.as_markup()
        else:
            text = "Unknown admin section."
        await cb.answer()
        if cb.message:
            await cb.message.answer(text, reply_markup=section_markup)
    except Exception:
        log.exception("Admin section %s failed for user %s", section, cb.from_user.id)
        await cb.answer("Section load nahi hua. Render Logs check karein.", show_alert=True)



@router.callback_query(F.data.startswith(("admin:disable_force:", "admin:enable_force:")))
async def toggle_force_channel(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    action, raw_id = cb.data.rsplit(":", 1)
    try:
        channel_id = int(raw_id)
    except ValueError:
        await cb.answer("Invalid channel ID.", show_alert=True)
        return
    active = action == "admin:enable_force"
    await db().execute("UPDATE force_channels SET is_active=$1 WHERE channel_id=$2", active, channel_id)
    await cb.answer("Channel enabled." if active else "Channel disabled.")
    if cb.message:
        await cb.message.answer("Channel status update ho gaya. Force Join section dobara kholkar check karein.", reply_markup=admin_keyboard())


@router.message(Command("checkin", "check"))
async def checkin(msg: Message):
    if not await is_admin(msg.from_user.id): return
    parts=(msg.text or "").split(maxsplit=1)
    if len(parts)!=2:
        await msg.answer("Usage: /checkin EVT-XXXXXXXXXX"); return
    code=parts[1].strip()
    async with db().acquire() as conn:
        async with conn.transaction():
            row=await conn.fetchrow("""SELECT t.*,o.status FROM tickets t JOIN orders o USING(order_id)
                WHERE t.ticket_code=$1 FOR UPDATE OF t""",code)
            if not row or row["status"]!="paid" or not row["delivered_at"]:
                await msg.answer("Ticket invalid hai ya payment/delivery confirm nahi hai."); return
            if row["checked_in_at"]:
                await msg.answer("Ticket pehle hi check-in ho chuka hai."); return
            await conn.execute("UPDATE tickets SET checked_in_at=NOW(),checked_in_by=$1,is_checked_in=TRUE WHERE ticket_id=$2",msg.from_user.id,row["ticket_id"])
    await msg.answer(f"✅ Check-in successful: <code>{code}</code>")

@router.message(Command("info"))
async def ticket_info(msg: Message):
    if not await is_admin(msg.from_user.id):
        return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await msg.answer("Usage: /info EVT-XXXXXXXXXX")
        return
    code = parts[1].strip().upper()
    row = await db().fetchrow(
        """SELECT t.ticket_code, t.user_id, t.created_at, t.delivered_at, t.checked_in_at,
                  o.status, o.amount, o.currency
           FROM tickets t JOIN orders o USING(order_id) WHERE t.ticket_code=$1""", code
    )
    if not row:
        await msg.answer("❌ Ticket nahi mila.")
        return
    status = "🔴 USED" if row["checked_in_at"] else ("🟢 VALID" if row["status"] == "paid" and row["delivered_at"] else "🟡 PENDING")
    await msg.answer(
        f"🎟 <b>Ticket Info</b>\nCode: <code>{row['ticket_code']}</code>\nStatus: {status}"
        f"\nPayment: {row['status']}\nAmount: {row['amount']} {row['currency']}"
        f"\nUser: <code>{row['user_id']}</code>\nIssued: {row['created_at']}"
        f"\nChecked in: {row['checked_in_at'] or '—'}"
    )


class SupportReplyFSM(StatesGroup):
    waiting_reply = State()


@router.callback_query(F.data.startswith("sup:view:"))
async def support_view(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    try:
        ticket_id = int(cb.data.rsplit(":", 1)[1])
    except (ValueError, AttributeError):
        await cb.answer("Invalid support ticket.", show_alert=True)
        return
    ticket = await db().fetchrow(
        """SELECT s.id,s.user_id,s.status,COALESCE(s.full_name,'') AS full_name,
                  COALESCE(s.username,'') AS username,COALESCE(s.query,s.message,'') AS query
           FROM support_tickets s WHERE s.id=$1""",
        ticket_id,
    )
    if not ticket:
        await cb.answer("Ticket nahi mila.", show_alert=True)
        return
    messages = await db().fetch(
        "SELECT sender_role,message_text,created_at FROM support_messages WHERE ticket_id=$1 ORDER BY id ASC LIMIT 50",
        ticket_id,
    )
    text = (
        f"🆘 <b>Support #{ticket_id}</b> — {ticket['status']}\n"
        f"👤 {ticket['full_name'] or 'Unknown'} (@{ticket['username'] or '—'})\n"
        f"🆔 <code>{ticket['user_id']}</code>\n\n"
    )
    if not messages:
        text += f"User: {ticket['query']}\n"
    else:
        for item in messages[-20:]:
            who = "👤 User" if item["sender_role"] == "user" else "🛠 Admin"
            text += f"{who}: {item['message_text'][:700]}\n\n"
    kb = InlineKeyboardBuilder()
    if ticket["status"] == "open":
        kb.button(text="✍️ Reply to User", callback_data=f"sup:reply:{ticket_id}")
        kb.button(text="🔒 Close Ticket", callback_data=f"sup:close:{ticket_id}")
    kb.button(text="🔄 Refresh", callback_data=f"sup:view:{ticket_id}")
    kb.button(text="⬅️ Support List", callback_data="admin:support")
    kb.adjust(1)
    await cb.answer()
    if cb.message:
        await cb.message.answer(text[:3900], reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("sup:reply:"))
async def support_reply_start(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    try:
        ticket_id = int(cb.data.rsplit(":", 1)[1])
    except (ValueError, AttributeError):
        await cb.answer("Invalid support ticket.", show_alert=True)
        return
    row = await db().fetchrow(
        "SELECT id, status FROM support_tickets WHERE id=$1", ticket_id
    )
    if not row or row["status"] != "open":
        await cb.answer("Ticket missing or already closed.", show_alert=True)
        return
    await state.set_state(SupportReplyFSM.waiting_reply)
    await state.update_data(support_ticket_id=ticket_id)
    await cb.answer()
    await cb.message.answer(f"Support #{ticket_id} ka reply bhejein. Cancel: /cancel")


@router.message(SupportReplyFSM.waiting_reply)
async def support_reply_send(msg: Message, state: FSMContext, bot: Bot):
    if not await is_admin(msg.from_user.id):
        await state.clear()
        return
    raw_reply = (msg.text or "").strip()
    if not raw_reply:
        await msg.answer("Text reply bhejein. Cancel: /cancel")
        return
    if raw_reply.split(maxsplit=1)[0].split("@", 1)[0] == "/cancel":
        await state.clear()
        await msg.answer("Reply cancelled.")
        return
    reply_text = raw_reply[:2000]
    data = await state.get_data()
    ticket_id = data.get("support_ticket_id")
    row = await db().fetchrow(
        "SELECT user_id, status FROM support_tickets WHERE id=$1", ticket_id
    )
    if not row or row["status"] != "open":
        await state.clear()
        await msg.answer("Support ticket open nahi hai.")
        return
    await db().execute(
        "UPDATE support_tickets SET admin_reply=$1,replied_by=$2,replied_at=NOW() WHERE id=$3 AND status='open'",
        reply_text, msg.from_user.id, ticket_id
    )
    await db().execute(
        "INSERT INTO support_messages(ticket_id,sender_id,sender_role,message_text) VALUES($1,$2,'admin',$3)",
        ticket_id, msg.from_user.id, reply_text,
    )
    try:
        user_kb = InlineKeyboardBuilder()
        user_kb.button(text="📂 Open Support Conversation", callback_data=f"support:open:{ticket_id}")
        await bot.send_message(
            row["user_id"],
            f"💬 <b>Support reply #{ticket_id}</b>\n\n{reply_text}",
            reply_markup=user_kb.as_markup(),
        )
    except Exception:
        log.exception("Failed to deliver support reply for ticket %s", ticket_id)
        await msg.answer("Reply database mein save hua, lekin user ko message deliver nahi hua.")
        await state.clear()
        return
    await state.clear()
    await msg.answer(f"✅ Support #{ticket_id} ka reply bhej diya.")


@router.callback_query(F.data.startswith("sup:close:"))
async def support_close(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    try:
        ticket_id = int(cb.data.rsplit(":", 1)[1])
    except (ValueError, AttributeError):
        await cb.answer("Invalid support ticket.", show_alert=True)
        return
    updated = await db().fetchval(
        "UPDATE support_tickets SET status='closed' WHERE id=$1 AND status='open' RETURNING id",
        ticket_id,
    )
    if updated:
        await cb.answer("Support ticket closed.")
        await cb.message.answer(f"🔒 Support #{ticket_id} closed by admin.")
    else:
        await cb.answer("Ticket missing or already closed.", show_alert=True)


class AdminEditFSM(StatesGroup):
    edit_tier = State()
    edit_setting = State()
    edit_menu = State()
    add_admin = State()
    remove_admin = State()
    add_force = State()
    add_file = State()
    add_promo = State()


@router.callback_query(F.data == "admin:add_promo")
async def add_promo_start(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    await state.set_state(AdminEditFSM.add_promo)
    await cb.answer()
    await cb.message.answer(
        "🎁 Promo code banayein. Format: <code>CODE | max uses</code>\n"
        "Example: <code>FREEENTRY | 1</code>\n"
        "Max uses mein 1 ya usse zyada number dein. Har user ek code sirf ek baar redeem kar sakta hai.\n"
        "Cancel: /cancel"
    )


@router.message(AdminEditFSM.add_promo, F.text)
async def add_promo_save(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        await state.clear()
        return
    raw = (msg.text or "").strip()
    if raw.split(maxsplit=1)[0].split("@", 1)[0] == "/cancel":
        await state.clear()
        await msg.answer("Promo creation cancelled.")
        return
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) != 2 or not parts[0] or not parts[1].isdigit() or int(parts[1]) < 1:
        await msg.answer("Format: CODE | max uses\nExample: FREEENTRY | 1")
        return
    code = parts[0].upper()
    if len(code) > 40 or not all(ch.isalnum() or ch in "_-" for ch in code):
        await msg.answer("Code mein sirf A-Z, 0-9, underscore ya hyphen use karein.")
        return
    try:
        await db().execute(
            "INSERT INTO promo_codes(code,max_uses,created_by) VALUES($1,$2,$3)",
            code, int(parts[1]), msg.from_user.id
        )
    except Exception:
        log.exception("Could not create promo code %s", code)
        await msg.answer("Yeh code pehle se maujood hai ya save nahi hua. Naya code try karein.")
        return
    await state.clear()
    await msg.answer(f"✅ Promo code <code>{code}</code> create ho gaya. Max redemptions: {parts[1]}. Ab aap ise users ko de sakte hain.")


@router.callback_query(F.data.startswith(("admin:disable_promo:", "admin:enable_promo:")))
async def toggle_promo(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    action, code = cb.data.rsplit(":", 1)
    active = action == "admin:enable_promo"
    if active:
        # Reactivation starts a fresh usage cycle while preserving old redemption history.
        updated = await db().fetchval(
            """UPDATE promo_codes
               SET is_active=TRUE, uses_count=0, activation_cycle=activation_cycle+1
               WHERE code=$1 AND is_active=FALSE RETURNING code""",
            code,
        )
        if not updated:
            updated = await db().fetchval(
                "UPDATE promo_codes SET is_active=TRUE WHERE code=$1 RETURNING code",
                code,
            )
    else:
        updated = await db().fetchval(
            "UPDATE promo_codes SET is_active=FALSE WHERE code=$1 RETURNING code",
            code,
        )
    if not updated:
        await cb.answer("Promo code nahi mila.", show_alert=True)
        return
    await cb.answer("Promo code enabled." if active else "Promo code disabled.")
    if cb.message:
        await cb.message.answer("Promo code status update ho gaya. Admin → Promo Codes dobara kholkar verify karein.")


@router.callback_query(F.data.startswith("admin:reactivate_promo:"))
async def reactivate_promo(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    code = cb.data.rsplit(":", 1)[1]
    updated = await db().fetchval(
        """UPDATE promo_codes
           SET is_active=TRUE, uses_count=0, activation_cycle=activation_cycle+1
           WHERE code=$1 RETURNING code""",
        code,
    )
    if not updated:
        await cb.answer("Promo code nahi mila.", show_alert=True)
        return
    await cb.answer("Promo reactivated; usage limit reset ho gayi.")
    if cb.message:
        await cb.message.answer(
            f"♻️ Promo <code>{code}</code> reactivate ho gaya. Usage counter reset hai; purani redemption history preserved hai."
        )


@router.callback_query(F.data.startswith("admin:delete_promo:"))
async def delete_promo(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    code = cb.data.rsplit(":", 1)[1]
    used = await db().fetchval("SELECT EXISTS(SELECT 1 FROM promo_redemptions WHERE code=$1)", code)
    if used:
        await db().execute("UPDATE promo_codes SET is_active=FALSE WHERE code=$1", code)
        await cb.answer("Code use ho chuka hai; history preserve karne ke liye disable kiya.", show_alert=True)
    else:
        deleted = await db().fetchval("DELETE FROM promo_codes WHERE code=$1 RETURNING code", code)
        await cb.answer("Promo code delete ho gaya." if deleted else "Promo code nahi mila.", show_alert=True)


@router.callback_query(F.data.startswith("admin:edit_tier:"))
async def edit_tier_start(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True); return
    tier_id = int(cb.data.rsplit(":", 1)[1])
    row = await db().fetchrow("SELECT * FROM ticket_types WHERE id=$1", tier_id)
    if not row:
        await cb.answer("Ticket type nahi mila.", show_alert=True); return
    await state.set_state(AdminEditFSM.edit_tier)
    await state.update_data(tier_id=tier_id)
    await cb.answer()
    await cb.message.answer(
        f"🎟 <b>{row['label']}</b> edit karne ke liye ek line bhejein:\n"
        "<code>Name | INR rupees | Stars | yes/no</code>\n"
        "Example: General Ticket | 599 | 60 | yes\n"
        "Cancel: /cancel"
    )


@router.message(AdminEditFSM.edit_tier, F.text)
async def edit_tier_save(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id): await state.clear(); return
    if (msg.text or "").strip().split(maxsplit=1)[0].split("@",1)[0] == "/cancel":
        await state.clear(); await msg.answer("Edit cancelled."); return
    parts=[p.strip() for p in (msg.text or "").split("|")]
    if len(parts)!=4 or not parts[0] or not parts[1].isdigit() or not parts[2].isdigit() or parts[3].lower() not in ("yes","no","true","false","on","off"):
        await msg.answer("Format galat hai. Use: Name | INR rupees | Stars | yes/no"); return
    inr, stars=int(parts[1]),int(parts[2])
    if inr<1 or stars<1:
        await msg.answer("Price 0 se zyada hona chahiye."); return
    data=await state.get_data()
    await db().execute("UPDATE ticket_types SET label=$1,price_inr=$2,price_stars=$3,is_active=$4,updated_at=NOW() WHERE id=$5",
        parts[0][:100],inr*100,stars,parts[3].lower() in ("yes","true","on"),data["tier_id"])
    await state.clear()
    await msg.answer(f"✅ Ticket update ho gaya: {parts[0]} — ₹{inr} / ⭐{stars}. /admin kholkar Ticket Types refresh karein.")


@router.callback_query(F.data.startswith("admin:edit_setting:"))
async def edit_setting_start(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id): await cb.answer("Admin only.",show_alert=True); return
    key=cb.data.rsplit(":",1)[1]
    allowed={"event_name":"Event name","event_date":"Event date","venue":"Venue","welcome_msg":"Welcome message"}
    if key not in allowed: await cb.answer("Setting allowed nahi hai.",show_alert=True); return
    await state.set_state(AdminEditFSM.edit_setting); await state.update_data(setting_key=key)
    await cb.answer()
    await cb.message.answer(f"✏️ {allowed[key]} ka naya value bhejein (max 500 characters). Cancel: /cancel")


@router.message(AdminEditFSM.edit_setting, F.text)
async def edit_setting_save(msg: Message,state:FSMContext):
    if not await is_admin(msg.from_user.id): await state.clear(); return
    if (msg.text or "").strip().split(maxsplit=1)[0].split("@",1)[0] == "/cancel":
        await state.clear(); await msg.answer("Edit cancelled."); return
    value=(msg.text or "").strip()
    if not value or value.startswith("/cancel"): await state.clear(); await msg.answer("Cancelled."); return
    data=await state.get_data()
    await db().execute("INSERT INTO bot_settings(key,value,updated_at) VALUES($1,$2,NOW()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=NOW()",data["setting_key"],value[:500])
    await state.clear(); await msg.answer("✅ Setting save ho gayi. /admin se verify karein.")


@router.callback_query(F.data.startswith("admin:edit_menu:"))
async def edit_menu_start(cb:CallbackQuery,state:FSMContext):
    if not await is_admin(cb.from_user.id): await cb.answer("Admin only.",show_alert=True); return
    key=cb.data.rsplit(":",1)[1]
    row=await db().fetchrow("SELECT * FROM user_menu WHERE key=$1",key)
    if not row: await cb.answer("Menu item nahi mila.",show_alert=True); return
    await state.set_state(AdminEditFSM.edit_menu); await state.update_data(menu_key=key)
    await cb.answer()
    await cb.message.answer(f"✏️ Current button name: <b>{row['label']}</b>\nSirf naya button name bhejein (max 50 characters).\nIs button ka action change nahi hoga; sirf naam badlega.\nCancel: /cancel")


@router.message(AdminEditFSM.edit_menu,F.text)
async def edit_menu_save(msg:Message,state:FSMContext):
    if not await is_admin(msg.from_user.id): await state.clear(); return
    if (msg.text or "").strip().split(maxsplit=1)[0].split("@",1)[0] == "/cancel":
        await state.clear(); await msg.answer("Edit cancelled."); return
    label=(msg.text or "").strip()
    if not label or len(label)>50:
        await msg.answer("Button name 1–50 characters ka bhejein. Cancel: /cancel"); return
    d=await state.get_data()
    await db().execute("UPDATE user_menu SET label=$1 WHERE key=$2",label,d["menu_key"])
    await state.clear()
    await msg.answer(f"✅ Button ka naam update ho gaya: <b>{label}</b>\nUser ko naya menu dikhane ke liye /start dobara chalayein. Action pehle jaisa hi rahega.")


@router.callback_query(F.data.startswith(("admin:disable_menu:", "admin:enable_menu:")))
async def toggle_menu_item(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    action, key = cb.data.rsplit(":", 1)
    active = action == "admin:enable_menu"
    updated = await db().fetchval(
        "UPDATE user_menu SET is_active=$1 WHERE key=$2 RETURNING key",
        active, key
    )
    if not updated:
        await cb.answer("Menu item nahi mila.", show_alert=True)
        return
    await cb.answer("Menu item visible." if active else "Menu item hidden.")
    if cb.message:
        await cb.message.answer(
            "✅ Menu visibility update ho gayi. User ko updated menu dikhane ke liye /start dobara chalayein.",
            reply_markup=admin_keyboard()
        )


@router.callback_query(F.data == "admin:add_admin")
async def add_admin_start(cb:CallbackQuery,state:FSMContext):
    if not await is_admin(cb.from_user.id): await cb.answer("Admin only.",show_alert=True); return
    await state.set_state(AdminEditFSM.add_admin); await cb.answer()
    await cb.message.answer("Naye admin ka numeric Telegram user ID bhejein. Cancel: /cancel")


@router.message(AdminEditFSM.add_admin,F.text)
async def add_admin_save(msg:Message,state:FSMContext):
    if not await is_admin(msg.from_user.id): await state.clear(); return
    raw=(msg.text or "").strip()
    if raw=="/cancel": await state.clear(); await msg.answer("Cancelled."); return
    if not raw.isdigit(): await msg.answer("Sirf numeric Telegram ID bhejein."); return
    uid=int(raw)
    await db().execute("INSERT INTO admins(telegram_id,added_by,is_active) VALUES($1,$2,TRUE) ON CONFLICT(telegram_id) DO UPDATE SET is_active=TRUE,added_by=EXCLUDED.added_by",uid,msg.from_user.id)
    await state.clear(); await msg.answer(f"✅ Admin {uid} add/activate ho gaya.")


@router.callback_query(F.data == "admin:remove_admin")
async def remove_admin_start(cb:CallbackQuery,state:FSMContext):
    if not await is_admin(cb.from_user.id): await cb.answer("Admin only.",show_alert=True); return
    await state.set_state(AdminEditFSM.remove_admin); await cb.answer()
    await cb.message.answer("Remove karne ke liye database admin ka numeric Telegram ID bhejein. Render ADMIN_IDS se added admin ko yahan se remove nahi kar sakte.")


@router.message(AdminEditFSM.remove_admin,F.text)
async def remove_admin_save(msg:Message,state:FSMContext):
    if not await is_admin(msg.from_user.id): await state.clear(); return
    raw=(msg.text or "").strip()
    if raw=="/cancel": await state.clear(); await msg.answer("Cancelled."); return
    if not raw.isdigit(): await msg.answer("Sirf numeric Telegram ID bhejein."); return
    uid=int(raw)
    from config import ADMIN_IDS
    if uid in ADMIN_IDS:
        await msg.answer("Yeh ID Render ADMIN_IDS mein hai. Wahan se remove karke redeploy karna hoga."); await state.clear(); return
    await db().execute("UPDATE admins SET is_active=FALSE WHERE telegram_id=$1",uid)
    await state.clear(); await msg.answer(f"✅ Admin {uid} inactive kar diya.")


@router.callback_query(F.data == "admin:add_force")
async def add_force_start(cb:CallbackQuery,state:FSMContext):
    if not await is_admin(cb.from_user.id): await cb.answer("Admin only.",show_alert=True); return
    await state.set_state(AdminEditFSM.add_force); await cb.answer()
    await cb.message.answer("Channel details bhejein:\n<code>numeric_channel_id | @username | invite_link</code>\nExample: -1001234567890 | @mychannel | https://t.me/mychannel\nBot ko channel mein admin hona chahiye.")


@router.message(AdminEditFSM.add_force,F.text)
async def add_force_save(msg:Message,state:FSMContext):
    if not await is_admin(msg.from_user.id): await state.clear(); return
    p=[x.strip() for x in (msg.text or "").split("|")]
    if len(p)!=3 or not p[0].lstrip("-").isdigit():
        await msg.answer("Format: numeric_channel_id | @username | invite_link"); return
    channel_id=int(p[0]); username=p[1].lstrip("@") or None; invite=p[2] or None
    await db().execute("INSERT INTO force_channels(channel_id,channel_username,invite_link,is_active,added_by) VALUES($1,$2,$3,TRUE,$4) ON CONFLICT(channel_id) DO UPDATE SET channel_username=EXCLUDED.channel_username,invite_link=EXCLUDED.invite_link,is_active=TRUE,added_by=EXCLUDED.added_by",channel_id,username,invite,msg.from_user.id)
    await state.clear(); await msg.answer("✅ Force-join channel save ho gaya. Bot ka membership check karne ke liye bot ko channel admin rakhein.")


@router.callback_query(F.data.startswith("admin:add_file:"))
async def add_file_start(cb:CallbackQuery,state:FSMContext):
    if not await is_admin(cb.from_user.id): await cb.answer("Admin only.",show_alert=True); return
    tier_id=int(cb.data.rsplit(":",1)[1])
    tier=await db().fetchrow("SELECT id,label FROM ticket_types WHERE id=$1",tier_id)
    if not tier: await cb.answer("Ticket type nahi mila.",show_alert=True); return
    await state.set_state(AdminEditFSM.add_file); await state.update_data(file_tier_id=tier_id)
    await cb.answer()
    await cb.message.answer(f"📁 {tier['label']} ke liye ab document/photo ya text message bhejein. Cancel: /cancel")


@router.message(AdminEditFSM.add_file)
async def add_file_save(msg:Message,state:FSMContext,bot:Bot):
    if not await is_admin(msg.from_user.id): await state.clear(); return
    if msg.text and msg.text.strip()=="/cancel": await state.clear(); await msg.answer("Cancelled."); return
    data=await state.get_data(); tier_id=data["file_tier_id"]
    if msg.document:
        file_type="document"; file_id=msg.document.file_id; text_content=None; file_name=msg.document.file_name; mime=msg.document.mime_type; size=msg.document.file_size; caption=msg.caption
    elif msg.photo:
        file_type="photo"; file_id=msg.photo[-1].file_id; text_content=None; file_name=None; mime="image/jpeg"; size=msg.photo[-1].file_size; caption=msg.caption
    elif msg.text:
        file_type="text"; file_id=None; text_content=msg.text[:4000]; file_name=None; mime=None; size=None; caption=None
    else:
        await msg.answer("Document, photo ya text bhejein."); return
    await db().execute("INSERT INTO ticket_files(ticket_type_id,file_type,telegram_file_id,file_id,text_content,is_active,added_by,file_name,mime_type,file_size,caption) VALUES($1,$2,$3,$3,$4,TRUE,$5,$6,$7,$8,$9)",tier_id,file_type,file_id,text_content,msg.from_user.id,file_name,mime,size,caption)
    await state.clear(); await msg.answer("✅ File/content save ho gaya. Note: delivery flow mein ise use karne ka support alag se verify karna hoga.")


@router.callback_query(F.data.startswith(("admin:menu_move_up:", "admin:menu_move_down:")))
async def move_user_menu_item(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    action, key = cb.data.rsplit(":", 1)
    direction = -1 if action == "admin:menu_move_up" else 1
    async with db().acquire() as conn:
        async with conn.transaction():
            current = await conn.fetchrow("SELECT key,position FROM user_menu WHERE key=$1 FOR UPDATE", key)
            if not current:
                await cb.answer("Menu item nahi mila.", show_alert=True)
                return
            neighbor = await conn.fetchrow(
                "SELECT key,position FROM user_menu WHERE position " + ("<" if direction < 0 else ">") + " $1 ORDER BY position " + ("DESC" if direction < 0 else "ASC") + " LIMIT 1 FOR UPDATE",
                current["position"],
            )
            if not neighbor:
                await cb.answer("Is direction mein aur item nahi hai.")
                return
            await conn.execute("UPDATE user_menu SET position=$1 WHERE key=$2", neighbor["position"], current["key"])
            await conn.execute("UPDATE user_menu SET position=$1 WHERE key=$2", current["position"], neighbor["key"])
    await cb.answer("Menu order update ho gaya.")
    if cb.message:
        await cb.message.answer("🧭 Menu order update ho gaya. Latest order dekhne ke liye User Menu dobara kholein.", reply_markup=admin_keyboard())


@router.callback_query(F.data.startswith("admin:delete_file_confirm:"))
async def delete_ticket_file_confirm(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    try:
        file_id = int(cb.data.rsplit(":", 1)[1])
    except (ValueError, AttributeError):
        await cb.answer("Invalid file ID.", show_alert=True)
        return
    row = await db().fetchrow(
        "SELECT f.id, t.label, f.file_type FROM ticket_files f JOIN ticket_types t ON t.id=f.ticket_type_id WHERE f.id=$1",
        file_id,
    )
    if not row:
        await cb.answer("Ticket file nahi mili.", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Yes, permanently delete", callback_data=f"admin:delete_file_do:{file_id}")
    kb.button(text="❌ Cancel", callback_data="admin:files")
    kb.adjust(1)
    await cb.answer()
    await cb.message.answer(
        f"⚠️ <b>Confirm file deletion</b>\n\n"
        f"File: <b>#{row['id']}</b> — {row['label']} ({row['file_type']})\n"
        "Is action se ticket_files database record permanently delete ho jayega. Existing issued tickets/history delete nahi honge.\n\n"
        "Kya aap continue karna chahte hain?",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("admin:delete_file_do:"))
async def delete_ticket_file_do(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    try:
        file_id = int(cb.data.rsplit(":", 1)[1])
    except (ValueError, AttributeError):
        await cb.answer("Invalid file ID.", show_alert=True)
        return
    deleted = await db().fetchval(
        "DELETE FROM ticket_files WHERE id=$1 RETURNING id",
        file_id,
    )
    if not deleted:
        await cb.answer("File pehle hi delete ho chuki hai.", show_alert=True)
        return
    await cb.answer("Ticket file permanently deleted.")
    if cb.message:
        await cb.message.edit_text(
            f"✅ Ticket file #{deleted} permanently delete ho gayi.\n\n"
            "Baaki files dekhne ke liye Ticket Files dobara kholein.",
            reply_markup=admin_keyboard(),
        )


class BroadcastFSM(StatesGroup):
    content = State()
    confirm = State()


@router.callback_query(F.data == "admin:broadcast")
async def broadcast_start(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    await state.set_state(BroadcastFSM.content)
    await cb.answer()
    if cb.message:
        await cb.message.answer(
            "📣 <b>Broadcast</b>\n\nAb woh message bhejein jo sabhi registered users ko bhejna hai. "
            "Text, photo, video ya document with caption bhej sakte hain.\n"
            "Cancel karne ke liye /cancel bhejein."
        )


@router.message(BroadcastFSM.content)
async def broadcast_receive(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        await state.clear()
        return
    if (msg.text or "").strip() == "/cancel":
        await state.clear()
        await msg.answer("❌ Broadcast cancel ho gaya.", reply_markup=admin_keyboard())
        return
    await state.update_data(source_chat_id=msg.chat.id, source_message_id=msg.message_id)
    await state.set_state(BroadcastFSM.confirm)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Send to all users", callback_data="admin:broadcast_send")
    kb.button(text="❌ Cancel", callback_data="admin:broadcast_cancel")
    kb.adjust(1)
    count = await db().fetchval("SELECT COUNT(*) FROM users")
    await msg.answer(
        f"📣 <b>Broadcast confirmation</b>\nRegistered recipients: <b>{count}</b>\n"
        "Confirm karne par ye message sabhi registered users ko bheja jayega.",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data == "admin:broadcast_cancel")
async def broadcast_cancel(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    await state.clear()
    await cb.answer("Broadcast cancelled.")
    if cb.message:
        await cb.message.answer("Broadcast cancel ho gaya.", reply_markup=admin_keyboard())


@router.callback_query(F.data == "admin:broadcast_send")
async def broadcast_send(cb: CallbackQuery, state: FSMContext, bot: Bot):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    data = await state.get_data()
    if not data.get("source_chat_id") or not data.get("source_message_id"):
        await state.clear()
        await cb.answer("Broadcast content nahi mila. Dobara try karein.", show_alert=True)
        return
    await state.clear()
    await cb.answer("Broadcast started.")
    rows = await db().fetch("SELECT telegram_id FROM users ORDER BY telegram_id")
    sent = failed = 0
    if cb.message:
        status = await cb.message.answer(f"⏳ Broadcast shuru: {len(rows)} users.")
    else:
        status = None
    for row in rows:
        uid = int(row["telegram_id"])
        try:
            await bot.copy_message(
                chat_id=uid,
                from_chat_id=int(data["source_chat_id"]),
                message_id=int(data["source_message_id"]),
            )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
            log.warning("Broadcast delivery failed for user %s", uid, exc_info=True)
    summary = f"📣 <b>Broadcast complete</b>\n✅ Sent: {sent}\n⚠️ Failed/blocked: {failed}\n👥 Total: {len(rows)}"
    if status:
        await status.edit_text(summary, reply_markup=admin_keyboard())
    await log_audit(cb.from_user.id, "broadcast", {"total": len(rows), "sent": sent, "failed": failed})
