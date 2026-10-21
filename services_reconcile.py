"""Retry paid-but-undelivered tickets and reconcile stale PhonePe payments.

PhonePe status checks fail closed until the merchant API is configured in
services_phonepe.py. Never mark an order paid from a redirect or an
unverified webhook.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from db import db
from services_phonepe import check_payment_status
from services_ticket import atomic_create_and_deliver

log = logging.getLogger("reconcile")
CHECK_INTERVAL = 10 * 60
MIN_AGE = 10 * 60
BATCH_SIZE = 50


async def _retry_paid_tickets(bot: Bot) -> None:
    # The delivery service owns its own lock/lease and idempotency guard.
    rows = await db().fetch(
        """
        SELECT o.order_id
        FROM orders o
        LEFT JOIN tickets t ON t.order_id = o.order_id
        WHERE o.status = 'paid'
          AND (t.ticket_id IS NULL OR (
              t.delivered_at IS NULL
              AND (t.delivery_started_at IS NULL
                   OR t.delivery_started_at < NOW() - INTERVAL '10 minutes')
          ))
        ORDER BY o.updated_at, o.created_at
        LIMIT $1
        """,
        BATCH_SIZE,
    )
    for row in rows:
        try:
            result = await atomic_create_and_deliver(bot, row["order_id"])
            if result not in ("already_delivered", "already_delivered_or_in_progress"):
                log.info("Ticket retry order=%s result=%s", row["order_id"], result)
        except Exception:
            log.exception("Ticket retry failed for order %s", row["order_id"])


async def reconcile_pending_orders(bot: Bot) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=MIN_AGE)
    rows = await db().fetch(
        """
        SELECT order_id FROM orders
        WHERE status = 'pending'
          AND gateway = 'phonepe'
          AND created_at < $1
        ORDER BY created_at
        LIMIT $2
        """,
        cutoff,
        BATCH_SIZE,
    )
    for row in rows:
        order_id = row["order_id"]
        try:
            # This function must query the configured merchant status API.
            # The current integration intentionally raises until configured.
            status = await check_payment_status(order_id)
        except Exception as exc:
            log.warning("PhonePe status check unavailable for %s: %s", order_id, exc)
            continue

        state = str(status.get("state") or status.get("status") or "").upper()
        if state in {"COMPLETED", "SUCCESS", "SUCCESSFUL"}:
            txn = status.get("transactionId") or status.get("transaction_id")
            if not txn:
                log.warning("PhonePe returned success without transaction ID for %s", order_id)
                continue
            async with db().acquire() as conn:
                async with conn.transaction():
                    updated = await conn.fetchval(
                        """
                        UPDATE orders
                        SET status = 'paid', paid_at = NOW(), gateway_txn_id = $1,
                            updated_at = NOW()
                        WHERE order_id = $2 AND status = 'pending'
                        RETURNING order_id
                        """,
                        str(txn),
                        order_id,
                    )
            if updated:
                await atomic_create_and_deliver(bot, order_id)
        elif state in {"FAILED", "CANCELLED", "EXPIRED"}:
            await db().execute(
                """
                UPDATE orders SET status = 'failed', updated_at = NOW()
                WHERE order_id = $1 AND status = 'pending'
                """,
                order_id,
            )


async def reconcile_once(bot: Bot) -> None:
    await reconcile_pending_orders(bot)
    await _retry_paid_tickets(bot)


async def reconcile_loop(bot: Bot) -> None:
    while True:
        try:
            await reconcile_once(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Reconciliation loop error")
        await asyncio.sleep(CHECK_INTERVAL)
