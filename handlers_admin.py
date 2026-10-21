import logging
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from config import EVENT_NAME
from db import db
from utils import is_admin
log = logging.getLogger(__name__)
router=Router()

@router.message(Command("admin"))
async def admin_panel(msg: Message):
    if not await is_admin(msg.from_user.id): return
    users=await db().fetchval("SELECT COUNT(*) FROM users")
    orders=await db().fetchval("SELECT COUNT(*) FROM orders")
    paid=await db().fetchval("SELECT COUNT(*) FROM orders WHERE status='paid'")
    tickets=await db().fetchval("SELECT COUNT(*) FROM tickets")
    await msg.answer(f"🛠️ <b>{EVENT_NAME} Admin</b>\nUsers: {users}\nOrders: {orders}\nPaid orders: {paid}\nTickets: {tickets}\n\nUse /checkin TICKET-CODE to check in a ticket.")

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
