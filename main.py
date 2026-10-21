import asyncio, logging, os
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN, PORT, validate_config
from db import init_db, close_db
from handlers_user import router as user_router
from middlewares import ThrottlingMiddleware, ForceJoinMiddleware
from handlers_payment import router as payment_router
from handlers_admin import router as admin_router
from services_reconcile import reconcile_loop
from webhook_server import app as web_app

logging.basicConfig(level=logging.INFO,format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

async def serve_web():
    server=uvicorn.Server(uvicorn.Config(web_app,host="0.0.0.0",port=PORT,log_level="info"))
    await server.serve()

async def main():
    validate_config()
    await init_db()
    bot=Bot(BOT_TOKEN,default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp=Dispatcher(storage=MemoryStorage())
    dp.message.middleware(ThrottlingMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware())
    dp.message.middleware(ForceJoinMiddleware())
    dp.callback_query.middleware(ForceJoinMiddleware())
    dp.include_router(admin_router)
    dp.include_router(payment_router)
    dp.include_router(user_router)
    tasks=[
      asyncio.create_task(dp.start_polling(bot,handle_signals=False,close_bot_session=False),name="telegram-polling"),
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
