import asyncio, logging
from db import db
from services_ticket import atomic_create_and_deliver
log=logging.getLogger(__name__)

async def reconcile_once(bot):
    rows=await db().fetch("SELECT order_id FROM orders WHERE status='paid' ORDER BY updated_at LIMIT 100")
    for row in rows:
        try: await atomic_create_and_deliver(bot,row["order_id"])
        except Exception: log.exception("Ticket retry failed for %s",row["order_id"])

async def reconcile_loop(bot):
    while True:
        try: await reconcile_once(bot)
        except Exception: log.exception("Reconciliation loop error")
        await asyncio.sleep(300)
