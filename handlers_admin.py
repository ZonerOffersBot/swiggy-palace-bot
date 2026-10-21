from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from config import EVENT_NAME
from db import db
from utils import is_admin
router=Router()

@router.message(Command("admin"))
async def admin_panel(msg: Message):
    if not await is_admin(msg.from_user.id): return
    users=await db().fetchval("SELECT COUNT(*) FROM users")
    orders=await db().fetchval("SELECT COUNT(*) FROM orders")
    paid=await db().fetchval("SELECT COUNT(*) FROM orders WHERE status='paid'")
    tickets=await db().fetchval("SELECT COUNT(*) FROM tickets")
    await msg.answer(f"🛠️ <b>{EVENT_NAME} Admin</b>\nUsers: {users}\nOrders: {orders}\nPaid orders: {paid}\nTickets: {tickets}\n\nUse /checkin TICKET-CODE to check in a ticket.")

@router.message(Command("checkin"))
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
            await conn.execute("UPDATE tickets SET checked_in_at=NOW(),checked_in_by=$1 WHERE ticket_id=$2",msg.from_user.id,row["ticket_id"])
    await msg.answer(f"✅ Check-in successful: <code>{code}</code>")
