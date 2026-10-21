import io
import json
import logging
import re
import secrets
import string
import uuid
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.types import BufferedInputFile

from config import EVENT_DATE, EVENT_NAME, VENUE
from db import db
from utils import get_setting

log = logging.getLogger(__name__)


def _ticket_prefix(key: str | None) -> str:
    prefix = re.sub(r"[^A-Z0-9]", "", (key or "NORM").upper())[:8]
    return prefix or "NORM"


def make_pdf(code, order_id, user_id, *, tier_label=None, event_name=None, event_date=None, venue=None):
    """Build a compact ticket PDF using the tier and event details captured at issue time."""
    from reportlab.pdfgen import canvas

    stream = io.BytesIO()
    pdf = canvas.Canvas(stream, pagesize=(420, 300))
    pdf.setTitle("Event Ticket")
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(30, 255, (event_name or EVENT_NAME)[:50])
    pdf.setFont("Helvetica", 12)
    pdf.drawString(30, 230, f"Ticket type: {(tier_label or 'Ticket')[:60]}")
    pdf.drawString(30, 205, f"Date: {(event_date or EVENT_DATE)[:80]}")
    pdf.drawString(30, 180, f"Venue: {(venue or VENUE)[:80]}")
    pdf.drawString(30, 145, f"Ticket code: {code}")
    pdf.drawString(30, 120, f"Order: {str(order_id)[:36]}")
    pdf.drawString(30, 95, f"Telegram ID: {user_id}")
    pdf.drawString(30, 55, "Present this PDF at event entry.")
    pdf.save()
    stream.seek(0)
    return stream.getvalue()


async def _send_tier_files(bot: Bot, user_id: int, ticket_type_id: int, ticket_code: str):
    """Send only active files assigned to the purchased tier."""
    rows = await db().fetch(
        """SELECT file_type, COALESCE(file_id, telegram_file_id) AS file_id,
                  text_content, file_name, mime_type, caption
           FROM ticket_files
           WHERE ticket_type_id=$1 AND is_active=TRUE
           ORDER BY position, id""",
        ticket_type_id,
    )
    for row in rows:
        file_type = row["file_type"]
        caption = row["caption"] or f"🎟️ Ticket resource for {ticket_code}"
        if file_type == "text":
            body = row["text_content"] or ""
            if not body.strip():
                log.warning("Skipping empty text ticket file for tier %s", ticket_type_id)
                continue
            filename = row["file_name"] or f"{ticket_code}-instructions.txt"
            await bot.send_document(
                user_id,
                BufferedInputFile(body.encode("utf-8"), filename=filename),
                caption=caption,
            )
        elif file_type == "photo":
            if not row["file_id"]:
                log.warning("Skipping photo ticket file %s without Telegram file_id", ticket_type_id)
                continue
            await bot.send_photo(user_id, row["file_id"], caption=caption)
        elif file_type == "document":
            if not row["file_id"]:
                log.warning("Skipping document ticket file %s without Telegram file_id", ticket_type_id)
                continue
            await bot.send_document(
                user_id,
                row["file_id"],
                caption=caption,
            )


async def atomic_create_and_deliver(bot: Bot, order_id):
    """Create one ticket and claim one delivery attempt per order.

    A row lock plus the delivery lease prevents concurrent reconciliation workers
    from sending the same ticket at the same time. The lease is released on a
    failed Telegram send so the reconciliation loop can retry.
    """
    async with db().acquire() as conn:
        async with conn.transaction():
            order = await conn.fetchrow(
                """SELECT o.*, tt.key AS tier_key, tt.label AS tier_label
                   FROM orders o LEFT JOIN ticket_types tt ON tt.id=o.ticket_type_id
                   WHERE o.order_id=$1 FOR UPDATE OF o""",
                order_id,
            )
            if not order or order["status"] != "paid":
                return "payment_not_confirmed"

            ticket = await conn.fetchrow(
                "SELECT * FROM tickets WHERE order_id=$1 FOR UPDATE",
                order_id,
            )
            if ticket and ticket["delivered_at"]:
                return "already_delivered"

            if not ticket:
                prefix = _ticket_prefix(order["tier_key"] if order else None)
                code = prefix + "-" + "".join(
                    secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6)
                )
                # Retry code collisions without ever reusing an existing ticket code.
                for attempt in range(5):
                    try:
                        ticket = await conn.fetchrow(
                            """INSERT INTO tickets
                               (ticket_id,order_id,user_id,ticket_code,ticket_type_id)
                               VALUES($1,$2,$3,$4,$5) RETURNING *""",
                            uuid.uuid4(), order_id, order["user_id"], code, order["ticket_type_id"],
                        )
                        break
                    except Exception as exc:
                        if getattr(exc, "sqlstate", None) != "23505" or attempt == 4:
                            raise
                        code = prefix + "-" + "".join(
                            secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6)
                        )

            if not order["ticket_type_id"]:
                log.error("Paid order %s has no ticket tier assigned", order_id)
                return "ticket_tier_missing"

            claimed = await conn.fetchrow(
                """UPDATE tickets SET delivery_started_at=NOW()
                   WHERE ticket_id=$1 AND delivered_at IS NULL
                     AND (delivery_started_at IS NULL
                          OR delivery_started_at < NOW() - INTERVAL '10 minutes')
                   RETURNING ticket_id, ticket_code, user_id, ticket_type_id""",
                ticket["ticket_id"],
            )
            if not claimed:
                return "already_delivered_or_in_progress"

    try:
        tier = await db().fetchrow(
            "SELECT key, label FROM ticket_types WHERE id=$1",
            claimed["ticket_type_id"],
        )
        event_name = await get_setting("event_name", EVENT_NAME)
        event_date = await get_setting("event_date", EVENT_DATE)
        venue = await get_setting("venue", VENUE)
        buyer = await db().fetchrow(
            "SELECT telegram_id, username, full_name, first_name FROM users WHERE telegram_id=$1",
            claimed["user_id"],
        )
        paid_order = await db().fetchrow(
            "SELECT order_id, amount, currency, gateway, gateway_txn_id, paid_at FROM orders WHERE order_id=$1",
            order_id,
        )
        metadata = {
            "ticket_code": claimed["ticket_code"],
            "ticket_type": {
                "key": tier["key"] if tier else "unknown",
                "label": tier["label"] if tier else "Ticket",
            },
            "buyer": {
                "telegram_id": claimed["user_id"],
                "username": buyer["username"] if buyer else None,
                "full_name": (buyer["full_name"] or buyer["first_name"]) if buyer else None,
            },
            "event": {"name": event_name, "date": event_date, "venue": venue},
            "payment": {
                "order_id": str(order_id),
                "amount": paid_order["amount"] if paid_order else None,
                "currency": paid_order["currency"] if paid_order else None,
                "gateway": paid_order["gateway"] if paid_order else None,
                "transaction_id": paid_order["gateway_txn_id"] if paid_order else None,
                "paid_at": paid_order["paid_at"].isoformat() if paid_order and paid_order["paid_at"] else None,
            },
            "issued_at": datetime.now(timezone.utc).isoformat(),
        }
        json_bytes = json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8")
        await bot.send_document(
            claimed["user_id"],
            BufferedInputFile(json_bytes, filename=f"{claimed['ticket_code']}-metadata.json"),
            caption=(
                f"🎟️ <b>{event_name}</b>\n"
                f"Ticket: <code>{claimed['ticket_code']}</code>\n"
                f"Type: {tier['label'] if tier else 'Ticket'}\n"
                "Keep the JSON metadata and ticket PDF for entry."
            ),
        )
        pdf = make_pdf(
            claimed["ticket_code"], order_id, claimed["user_id"],
            tier_label=tier["label"] if tier else "Ticket",
            event_name=event_name, event_date=event_date, venue=venue,
        )
        sent = await bot.send_document(
            claimed["user_id"],
            BufferedInputFile(pdf, filename=f"{claimed['ticket_code']}.pdf"),
            caption=f"🎟️ <b>{event_name}</b>\nTicket: <code>{claimed['ticket_code']}</code>",
        )
        await _send_tier_files(
            bot, claimed["user_id"], claimed["ticket_type_id"], claimed["ticket_code"]
        )
        updated = await db().fetchval(
            """UPDATE tickets
               SET pdf_file_id=$1, delivered_at=NOW(), delivered_to=$2,
                   is_delivered=TRUE, delivery_started_at=NULL
               WHERE ticket_id=$3 AND delivered_at IS NULL
               RETURNING ticket_id""",
            sent.document.file_id, claimed["user_id"], claimed["ticket_id"],
        )
        return "delivered" if updated else "already_delivered"
    except Exception:
        log.exception("Ticket delivery failed for order %s", order_id)
        await db().execute(
            "UPDATE tickets SET delivery_started_at=NULL WHERE ticket_id=$1 AND delivered_at IS NULL",
            claimed["ticket_id"],
        )
        return "delivery_failed"
