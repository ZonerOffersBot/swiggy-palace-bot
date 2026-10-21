import uuid, logging
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, LabeledPrice, PreCheckoutQuery, Message
from aiogram.exceptions import TelegramAPIError
from config import TICKET_PRICE_STARS, TICKET_PRICE_INR, PHONEPE_CLIENT_ID, PHONEPE_CLIENT_SECRET, WEBHOOK_BASE_URL
from db import db
from services_ticket import atomic_create_and_deliver
from utils import notify_admins
router=Router(); log=logging.getLogger(__name__)

@router.callback_query(F.data == "pay:stars")
async def pay_stars(cb: CallbackQuery, bot: Bot):
    await cb.answer()
    order_id=uuid.uuid4()
    await db().execute("""INSERT INTO orders(order_id,user_id,amount,currency,status,gateway,idempotency_key)
      VALUES($1,$2,$3,'XTR','pending','stars',$4)""",order_id,cb.from_user.id,TICKET_PRICE_STARS,str(order_id))
    try:
        await bot.send_invoice(chat_id=cb.from_user.id,title="Event Ticket",description="Digital event ticket PDF",
          payload=str(order_id),provider_token="",currency="XTR",
          prices=[LabeledPrice(label="Event Ticket",amount=TICKET_PRICE_STARS)])
    except TelegramAPIError:
        log.exception("Stars invoice could not be sent")
        await cb.message.answer("Invoice send nahi hua. Dobara try karein.")

@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    try:
        order=await db().fetchrow("SELECT * FROM orders WHERE order_id=$1",uuid.UUID(q.invoice_payload))
        ok=bool(order and order["user_id"]==q.from_user.id and order["status"]=="pending"
          and order["gateway"]=="stars" and order["currency"]=="XTR" and order["amount"]==q.total_amount and q.currency=="XTR")
        await q.answer(ok=ok,error_message=None if ok else "Order verify nahi hua. Naya invoice lein.")
    except Exception:
        log.exception("Pre-checkout validation failed")
        await q.answer(ok=False,error_message="Payment verify nahi ho paya. Dobara try karein.")

@router.message(F.successful_payment)
async def stars_paid(msg: Message, bot: Bot):
    p=msg.successful_payment
    try: oid=uuid.UUID(p.invoice_payload)
    except ValueError:
        await msg.answer("Payment reference invalid hai. Support se contact karein."); return
    async with db().acquire() as conn:
        async with conn.transaction():
            order=await conn.fetchrow("SELECT * FROM orders WHERE order_id=$1 FOR UPDATE",oid)
            if not order or order["user_id"]!=msg.from_user.id or order["gateway"]!="stars" or order["currency"]!="XTR" or order["amount"]!=p.total_amount or p.currency!="XTR":
                await msg.answer("Payment received but order validation failed. Admin ko notify kar diya.")
                await notify_admins(bot,f"⚠️ Stars payment validation mismatch. order={oid} user={msg.from_user.id}")
                return
            if order["status"]!="paid":
                await conn.execute("UPDATE orders SET status='paid',gateway_txn_id=$1,updated_at=NOW() WHERE order_id=$2",
                    p.telegram_payment_charge_id,oid)
    result=await atomic_create_and_deliver(bot,oid)
    if result!="delivered" and result!="already_delivered":
        await msg.answer("Payment successful hai, lekin ticket delivery pending hai. Please wait; system retry karega.")
        await notify_admins(bot,f"Ticket delivery needs retry: order {oid}, state={result}")

@router.callback_query(F.data == "pay:phonepe")
async def pay_phonepe(cb: CallbackQuery):
    await cb.answer()
    if not (PHONEPE_CLIENT_ID and PHONEPE_CLIENT_SECRET and WEBHOOK_BASE_URL):
        await cb.message.answer("PhonePe abhi configure nahi hai. Admin ko PhonePe merchant credentials Render Environment mein add karne honge.")
        return
    await cb.message.answer("PhonePe checkout abhi enable nahi kiya gaya: merchant-specific OAuth, checkout and webhook verification must be validated before accepting payments. Telegram Stars is available meanwhile.")
