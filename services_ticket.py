import io, secrets, string, uuid, logging
from datetime import datetime, timezone
from reportlab.pdfgen import canvas
from aiogram import Bot
from aiogram.types import BufferedInputFile
from db import db
from config import EVENT_NAME, EVENT_DATE, VENUE

log = logging.getLogger(__name__)

def make_pdf(code, order_id, user_id, event_name, event_date, venue):
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream, pagesize=(420, 300))
    pdf.setTitle(f"{event_name[:80]} — Ticket")
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(30, 255, event_name[:50])
    pdf.setFont("Helvetica", 12)
    pdf.drawString(30, 220, f"Date: {event_date[:80]}")
    pdf.drawString(30, 195, f"Venue: {venue[:80]}")
    pdf.drawString(30, 155, f"Ticket code: {code}")
    pdf.drawString(30, 130, f"Order: {str(order_id)[:36]}")
    pdf.drawString(30, 105, f"Telegram ID: {user_id}")
    pdf.drawString(30, 55, "Please keep this ticket ready at the entrance.")
    pdf.save()
    stream.seek(0)
    return stream.getvalue()

async def atomic_create_and_deliver(bot: Bot, order_id):
    # Lock the order and create exactly one ticket; DB constraints protect across processes.
    async with db().acquire() as conn:
        async with conn.transaction():
            order = await conn.fetchrow("SELECT * FROM orders WHERE order_id=$1 FOR UPDATE", order_id)
            if not order or order["status"] != "paid":
                return "payment_not_confirmed"
            ticket = await conn.fetchrow("SELECT * FROM tickets WHERE order_id=$1 FOR UPDATE", order_id)
            if ticket and ticket["delivered_at"]:
                return "already_delivered"
            if not ticket:
                code = "EVT-" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(10))
                ticket = await conn.fetchrow(
                    """INSERT INTO tickets(ticket_id,order_id,user_id,ticket_code,ticket_type_id)
                       VALUES($1,$2,$3,$4,$5) RETURNING *""",
                    uuid.uuid4(), order_id, order["user_id"], code, order["ticket_type_id"]
                )
            # Atomic delivery lease. Only one worker can claim an undelivered ticket.
            claimed = await conn.fetchrow(
                """UPDATE tickets SET delivery_started_at=NOW()
                   WHERE ticket_id=$1 AND delivered_at IS NULL
                     AND (delivery_started_at IS NULL OR delivery_started_at < NOW() - INTERVAL '10 minutes')
                   RETURNING ticket_id, ticket_code, user_id""",
                ticket["ticket_id"]
            )
            if not claimed:
                return "already_delivered_or_in_progress"
    try:
        from utils import get_setting
        event_name = await get_setting("event_name", EVENT_NAME)
        event_date = await get_setting("event_date", EVENT_DATE)
        venue = await get_setting("venue", VENUE)
        pdf = make_pdf(claimed["ticket_code"], order_id, claimed["user_id"], event_name, event_date, venue)
        sent = await bot.send_document(
            claimed["user_id"],
            BufferedInputFile(pdf, filename=f"{claimed['ticket_code']}.pdf"),
            caption=f"🎟️ <b>{event_name}</b>\nTicket code: <code>{claimed['ticket_code']}</code>\nPlease keep this PDF ready for entry."
        )
        updated = await db().fetchval(
            """UPDATE tickets SET pdf_file_id=$1, delivered_at=NOW(), delivery_started_at=NULL
               WHERE ticket_id=$2 AND delivered_at IS NULL RETURNING ticket_id""",
            sent.document.file_id, claimed["ticket_id"]
        )
        return "delivered" if updated else "already_delivered"
    except Exception:
        log.exception("Ticket delivery failed for order %s", order_id)
        # Release lease for a retry only when the send raised an error.
        await db().execute(
            "UPDATE tickets SET delivery_started_at=NULL WHERE ticket_id=$1 AND delivered_at IS NULL",
            claimed["ticket_id"]
        )
        return "delivery_failed"
