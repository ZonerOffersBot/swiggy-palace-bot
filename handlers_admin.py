import logging
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from config import EVENT_NAME
from db import db
from utils import is_admin
log = logging.getLogger(__name__)
router=Router()

def admin_keyboard():
    kb = InlineKeyboardBuilder()
    buttons = [
        ("📊 Stats", "admin:stats"), ("🎟 Ticket Types", "admin:tiers"),
        ("📁 Ticket Files", "admin:files"), ("⚙️ Settings", "admin:settings"),
        ("🧭 User Menu", "admin:menu"), ("📢 Force Join", "admin:force"),
        ("👮 Admins", "admin:admins"), ("🆘 Support", "admin:support"),
        ("🔄 Refresh", "admin:home"),
    ]
    for label, data in buttons:
        kb.button(text=label, callback_data=data)
    kb.adjust(2, 2, 2, 2, 1)
    return kb.as_markup()


async def admin_home_text():
    users = await db().fetchval("SELECT COUNT(*) FROM users")
    orders = await db().fetchval("SELECT COUNT(*) FROM orders")
    paid = await db().fetchval("SELECT COUNT(*) FROM orders WHERE status='paid'")
    tickets = await db().fetchval("SELECT COUNT(*) FROM tickets")
    return (f"🛠️ <b>{EVENT_NAME} Admin Panel</b>\\n\\n"
            f"👥 Users: {users}\\n🧾 Orders: {orders}\\n"
            f"✅ Paid orders: {paid}\\n🎟 Tickets issued: {tickets}\\n\\n"
            "Neeche kisi section ko select karein.")


@router.message(Command("admin"))
async def admin_panel(msg: Message):
    if not await is_admin(msg.from_user.id):
        await msg.answer(
            "⛔ Admin access nahi hai.\\n"
            f"Aapki Telegram ID: <code>{msg.from_user.id}</code>\\n\\n"
            "Render → Environment mein ADMIN_IDS ke andar ye ID add karein "
            "(multiple admins ke liye comma-separated IDs), phir service redeploy/restart karein."
        )
        return
    try:
        await msg.answer(await admin_home_text(), reply_markup=admin_keyboard())
    except Exception:
        log.exception("Admin panel failed for user %s", msg.from_user.id)
        await msg.answer("⚠️ Admin panel database error. Render Logs mein /admin ke baad wali traceback check karein.")


@router.callback_query(F.data.startswith("admin:"))
async def admin_navigation(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    section = cb.data.split(":", 1)[1]
    try:
        if section in ("home", "stats"):
            text = await admin_home_text()
        elif section == "tiers":
            rows = await db().fetch("SELECT id,label,price_inr,price_stars,is_active FROM ticket_types ORDER BY position,id")
            text = "🎟 <b>Ticket Types</b>\\n" + ("\\n".join(f"• {r['label']} — ₹{r['price_inr']/100:.2f} / ⭐ {r['price_stars']} — {'Active' if r['is_active'] else 'Inactive'} (ID {r['id']})" for r in rows) or "Abhi koi ticket type nahi hai.")
        elif section == "files":
            rows = await db().fetch("SELECT f.id,t.label,f.file_type,f.is_active FROM ticket_files f JOIN ticket_types t ON t.id=f.ticket_type_id ORDER BY f.position,f.id LIMIT 30")
            text = "📁 <b>Ticket Files (latest 30)</b>\\n" + ("\\n".join(f"• #{r['id']} — {r['label']} — {r['file_type']} — {'Active' if r['is_active'] else 'Inactive'}" for r in rows) or "Abhi koi ticket file add nahi hai.")
        elif section == "settings":
            rows = await db().fetch("SELECT key,value FROM bot_settings ORDER BY key")
            text = "⚙️ <b>Settings</b>\\n" + ("\\n".join(f"• <code>{r['key']}</code>: {r['value'][:150]}" for r in rows) or "Custom settings abhi set nahi hain.") + "\\nEvent defaults Render Environment se aate hain."
        elif section == "menu":
            rows = await db().fetch("SELECT key,label,is_active,position FROM user_menu ORDER BY position")
            text = "🧭 <b>User Menu</b>\\n" + ("\\n".join(f"• {r['position']}. {r['label']} — <code>{r['key']}</code> — {'Active' if r['is_active'] else 'Inactive'}" for r in rows) or "User menu empty hai.")
        elif section == "force":
            rows = await db().fetch("SELECT channel_id,channel_username,invite_link,is_active FROM force_channels ORDER BY id")
            text = "📢 <b>Force Join Channels</b>\\n" + ("\\n".join(f"• {r['channel_username'] or r['channel_id']} — {'Active' if r['is_active'] else 'Inactive'}" for r in rows) or "Koi force-join channel configured nahi hai.")
        elif section == "admins":
            rows = await db().fetch("SELECT telegram_id,is_active FROM admins ORDER BY telegram_id")
            text = "👮 <b>Database Admins</b>\\n" + ("\\n".join(f"• <code>{r['telegram_id']}</code> — {'Active' if r['is_active'] else 'Inactive'}" for r in rows) or "Database admins list empty hai. Render ADMIN_IDS admins ko bhi access deta hai.")
        elif section == "support":
            rows = await db().fetch("SELECT id,user_id,COALESCE(full_name,'') AS full_name,COALESCE(query,message,'') AS query,status,created_at FROM support_tickets ORDER BY created_at DESC LIMIT 15")
            text = "🆘 <b>Recent Support Tickets</b>\\n" + ("\\n\\n".join(f"#{r['id']} — {r['full_name'] or r['user_id']} — {r['status']}\\n{r['query'][:250]}" for r in rows) or "Abhi support tickets nahi hain.")
        else:
            text = "Unknown admin section."
        await cb.answer()
        if cb.message:
            await cb.message.answer(text, reply_markup=admin_keyboard())
    except Exception:
        log.exception("Admin section %s failed for user %s", section, cb.from_user.id)
        await cb.answer("Section load nahi hua. Render Logs check karein.", show_alert=True)


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
    if (msg.text or "").strip().split(maxsplit=1)[0].split("@", 1)[0] == "/cancel":
        await state.clear()
        await msg.answer("Reply cancelled.")
        return
    reply_text = (msg.text or "").strip()[:2000]
    if not reply_text:
        await msg.answer("Text reply bhejein. Cancel: /cancel")
        return
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
        "UPDATE support_tickets SET admin_reply=$1 WHERE id=$2 AND status='open'",
        reply_text, ticket_id
    )
    try:
        await bot.send_message(
            row["user_id"],
            f"💬 <b>Support reply #{ticket_id}</b>\n\n{reply_text}"
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
