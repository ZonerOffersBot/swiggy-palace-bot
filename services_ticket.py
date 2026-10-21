import io, secrets, string, uuid, asyncio, logging
from reportlab.pdfgen import canvas
from aiogram import Bot
from aiogram.types import BufferedInputFile
from db import db
from config import EVENT_NAME, EVENT_DATE, VENUE
log = logging.getLogger(__name__)
_locks = {}

def make_pdf(code, order_id, user_id):
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream, pagesize=(420, 300))
    pdf.setTitle("Event Ticket")
    pdf.setFont("Helvetica-Bold", 18); pdf.drawString(30, 255, EVENT_NAME[:50])
    pdf.setFont("Helvetica", 12)
    pdf.drawString(30, 220, f"Date: {EVENT_DATE[:80]}")
    pdf.drawString(30, 195, f"Venue: {VENUE[:80]}")
    pdf.drawString(30, 155, f"Ticket code: {code}")
    pdf.drawString(30, 130, f"Order: {str(order_id)[:36]}")
    pdf.drawString(30, 105, f"Telegram ID: {user_id}")
    pdf.drawString(30, 55, "Present this PDF at event entry.")
    pdf.save(); stream.seek(0); return stream.getvalue()

async def atomic_create_and_deliver(bot: Bot, order_id):
    lock = _locks.setdefault(str(order_id), asyncio.Lock())
    async with lock:
        async with db().acquire() as conn:
            async with conn.transaction():
                order = await conn.fetchrow("SELECT * FROM orders WHERE order_id=$1 FOR UPDATE", order_id)
                if not order or order["status"] != "paid": return "payment_not_confirmed"
                ticket = await conn.fetchrow("SELECT * FROM tickets WHERE order_id=$1", order_id)
                if ticket and ticket["delivered_at"]: return "already_delivered"
                if not ticket:
                    code = "EVT-" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(10))
                    ticket = await conn.fetchrow("""INSERT INTO tickets(ticket_id,order_id,user_id,ticket_code)
                        VALUES($1,$2,$3,$4) RETURNING *""", uuid.uuid4(), order_id, order["user_id"], code)
        try:
            pdf = make_pdf(ticket["ticket_code"], order_id, order["user_id"])
            sent = await bot.send_document(order["user_id"], BufferedInputFile(pdf, filename=f"{ticket['ticket_code']}.pdf"),
                caption=f"🎟️ <b>{EVENT_NAME}</b>\nTicket: <code>{ticket['ticket_code']}</code>\nKeep this PDF for entry.")
            await db().execute("UPDATE tickets SET pdf_file_id=$1, delivered_at=NOW() WHERE ticket_id=$2 AND delivered_at IS NULL",
                               sent.document.file_id, ticket["ticket_id"])
            return "delivered"
        except Exception:
            log.exception("Ticket delivery failed for order %s", order_id)
            return "delivery_failed"
