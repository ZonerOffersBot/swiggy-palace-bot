import asyncio, logging, os
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN, PORT, validate_config
from db import init_db, close_db
from handlers_user import router as user_router
from middlewares import ThrottlingMiddleware, ForceJoinMiddleware, BlacklistMiddleware
from handlers_payment import router as payment_router
from handlers_admin import router as admin_router
from handlers_wallet import router as wallet_router
from handlers_user_admin import router as user_admin_router
from services_reconcile import reconcile_loop
from webhook_server import app as web_app

logging.basicConfig(level=logging.INFO,format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

async def serve_web():
    server=uvicorn.Server(uvicorn.Config(web_app,host="0.0.0.0",port=PORT,log_level="info"))
    await server.serve()

async def run_single_poller(dp, bot):
    # PostgreSQL session lock prevents duplicate getUpdates polling across replicas.
    from db import db
    conn = await db().acquire()
    acquired = False
    try:
        # Render may briefly overlap old and new instances during deployment.
        # Do not wait forever after one failed lock attempt: keep retrying until
        # the previous poller exits and releases its PostgreSQL session lock.
        attempts = 0
        while not acquired:
            acquired = await conn.fetchval("SELECT pg_try_advisory_lock(731946220)")
            if acquired:
                break
            attempts += 1
            if attempts == 1:
                logging.warning("Telegram polling lock is held by another instance; retrying every 5 seconds.")
            elif attempts % 12 == 0:
                logging.warning("Telegram polling lock is still held after %s seconds; will keep retrying.", attempts * 5)
            await asyncio.sleep(5)
        logging.info("Telegram polling lock acquired; starting polling.")
        await dp.start_polling(bot, handle_signals=False, close_bot_session=False)
    finally:
        if acquired:
            try:
                await conn.execute("SELECT pg_advisory_unlock(731946220)")
            except Exception:
                logging.exception("Could not release polling advisory lock")
        await db().release(conn)


async def main():
    validate_config()
    await init_db()
    bot=Bot(BOT_TOKEN,default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # This bot uses long polling; remove any stale Telegram webhook while preserving queued updates.
    # PhonePe callbacks use the separate FastAPI route and are unaffected.
    await bot.delete_webhook(drop_pending_updates=False)
    dp=Dispatcher(storage=MemoryStorage())
    dp.message.middleware(ThrottlingMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware())
    dp.message.middleware(BlacklistMiddleware())
    dp.callback_query.middleware(BlacklistMiddleware())
    dp.message.middleware(ForceJoinMiddleware())
    dp.callback_query.middleware(ForceJoinMiddleware())
    dp.include_router(admin_router)
    dp.include_router(user_admin_router)
    dp.include_router(wallet_router)
    dp.include_router(payment_router)
    dp.include_router(user_router)
    tasks=[
      asyncio.create_task(run_single_poller(dp, bot),name="telegram-polling"),
      asyncio.create_task(serve_web(),name="web-server"),
      asyncio.create_task(reconcile_loop(bot),name="ticket-reconcile"),
    ]
    try:
        done,pending=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            exc=task.exception()
            if exc: raise exc
        raise RuntimeError("A long-running service task stopped unexpectedly.")
    finally:
        for task in tasks:
            if not task.done(): task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        await bot.session.close()
        await close_db()

if __name__=="__main__":
    asyncio.run(main())
