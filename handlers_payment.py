import uuid
import logging

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, LabeledPrice, PreCheckoutQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db import db
from services_ticket import atomic_create_and_deliver
from utils import notify_admins

router = Router()
log = logging.getLogger(__name__)


def _tier_price_label(price_inr: int) -> str:
    return f"₹{price_inr // 100}"


@router.callback_query(F.data == "menu:buy")
async def choose_tier(cb: CallbackQuery):
    tiers = await db().fetch(
        """SELECT id, key, label, price_inr, price_stars
           FROM ticket_types WHERE is_active=TRUE ORDER BY position, id"""
    )
    await cb.answer()
    if not tiers:
        await cb.message.answer("⚠️ Abhi koi ticket type available nahi hai.")
        return
    kb = InlineKeyboardBuilder()
    for tier in tiers:
        kb.button(
            text=f"{tier['label']} — {_tier_price_label(tier['price_inr'])} / ⭐{tier['price_stars']}",
            callback_data=f"tier:{tier['id']}",
        )
    kb.button(text="⬅️ Back", callback_data="user:home")
    kb.adjust(1)
    await cb.message.edit_text("🎫 <b>Ticket type chunein:</b>", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("tier:"))
async def choose_payment(cb: CallbackQuery):
    try:
        tier_id = int(cb.data.split(":", 1)[1])
    except (ValueError, AttributeError):
        await cb.answer("Invalid ticket type.", show_alert=True)
        return
    tier = await db().fetchrow(
        "SELECT * FROM ticket_types WHERE id=$1 AND is_active=TRUE", tier_id
    )
    if not tier:
        await cb.answer("Yeh ticket type ab available nahi hai.", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    kb.button(text=f"⭐ Telegram Stars ({tier['price_stars']})", callback_data=f"pay:stars:{tier_id}")
    kb.button(text=f"📱 UPI / PhonePe (temporarily unavailable)", callback_data=f"pay:phonepe:{tier_id}")
    kb.button(text="⬅️ Back", callback_data="menu:buy")
    kb.adjust(1)
    await cb.message.edit_text(
        f"🎫 <b>{tier['label']}</b>\n\nPayment method chunein:",
        reply_markup=kb.as_markup(),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("pay:stars:"))
async def pay_stars(cb: CallbackQuery, bot: Bot):
    try:
        tier_id = int(cb.data.split(":")[2])
    except (ValueError, IndexError, AttributeError):
        await cb.answer("Invalid ticket type.", show_alert=True)
        return
    tier = await db().fetchrow(
        "SELECT * FROM ticket_types WHERE id=$1 AND is_active=TRUE", tier_id
    )
    if not tier:
        await cb.answer("Ticket type ab available nahi hai.", show_alert=True)
        return
    order_id = uuid.uuid4()
    await db().execute(
        """INSERT INTO orders
           (order_id,user_id,amount,currency,status,gateway,idempotency_key,ticket_type_id)
           VALUES($1,$2,$3,'XTR','pending','stars',$4,$5)""",
        order_id, cb.from_user.id, tier["price_stars"], f"stars:{order_id}", tier_id,
    )
    await cb.answer()
    try:
        await bot.send_invoice(
            chat_id=cb.from_user.id,
            title=f"{tier['label']} — Event Ticket",
            description=f"Entry pass ({tier['key']})",
            payload=str(order_id),
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=tier["label"], amount=tier["price_stars"])],
        )
    except TelegramAPIError:
        log.exception("Could not send Stars invoice for order %s", order_id)
        await cb.message.answer("⚠️ Invoice send nahi hua. Dobara try karein.")


@router.pre_checkout_query()
async def pre_checkout(pcq: PreCheckoutQuery):
    try:
        order_id = uuid.UUID(pcq.invoice_payload)
        order = await db().fetchrow("SELECT * FROM orders WHERE order_id=$1", order_id)
        valid = bool(
            order
            and order["user_id"] == pcq.from_user.id
            and order["status"] == "pending"
            and order["gateway"] == "stars"
            and order["currency"] == "XTR"
            and order["amount"] == pcq.total_amount
            and pcq.currency == "XTR"
        )
        await pcq.answer(
            ok=valid,
            error_message=None if valid else "Order verify nahi hua. Naya invoice lein.",
        )
    except Exception:
        log.exception("Stars pre-checkout validation failed")
        await pcq.answer(ok=False, error_message="Payment verify nahi ho paya. Dobara try karein.")


@router.message(F.successful_payment)
async def stars_paid(msg: Message, bot: Bot):
    payment = msg.successful_payment
    try:
        order_id = uuid.UUID(payment.invoice_payload)
    except (ValueError, TypeError):
        await msg.answer("Payment reference invalid hai. Support se contact karein.")
        await notify_admins(bot, f"⚠️ Invalid Stars invoice payload from user {msg.from_user.id}")
        return

    async with db().acquire() as conn:
        async with conn.transaction():
            order = await conn.fetchrow("SELECT * FROM orders WHERE order_id=$1 FOR UPDATE", order_id)
            valid = bool(
                order
                and order["user_id"] == msg.from_user.id
                and order["gateway"] == "stars"
                and order["status"] in ("pending", "paid")
                and order["currency"] == "XTR"
                and order["amount"] == payment.total_amount
                and payment.currency == "XTR"
            )
            if not valid:
                mismatch = True
            else:
                mismatch = False
                if order["status"] != "paid":
                    await conn.execute(
                        """UPDATE orders SET status='paid', paid_at=COALESCE(paid_at,NOW()),
                           gateway_txn_id=$1, updated_at=NOW()
                           WHERE order_id=$2 AND status='pending'""",
                        payment.telegram_payment_charge_id, order_id,
                    )
                elif order["gateway_txn_id"] not in (None, payment.telegram_payment_charge_id):
                    mismatch = True

    if mismatch:
        await notify_admins(
            bot,
            f"⚠️ Stars payment/order validation mismatch. order={order_id} user={msg.from_user.id}",
        )
        await msg.answer("Payment/order verification issue hai. Admin ko notify kar diya.")
        return

    result = await atomic_create_and_deliver(bot, order_id)
    tier = await db().fetchrow(
        """SELECT tt.label FROM orders o LEFT JOIN ticket_types tt ON tt.id=o.ticket_type_id
           WHERE o.order_id=$1""",
        order_id,
    )
    if result == "delivered":
        await notify_admins(
            bot,
            f"💰 <b>Telegram Stars payment</b>\n🎫 {tier['label'] if tier else '?'}"
            f"\n⭐ {payment.total_amount} Stars\n👤 {msg.from_user.full_name}"
            f" (<code>{msg.from_user.id}</code>)\n🆔 <code>{str(order_id)[:8]}</code>",
        )
    elif result not in ("already_delivered", "already_delivered_or_in_progress"):
        await msg.answer("Payment successful hai, lekin ticket delivery pending hai. System retry karega.")
        await notify_admins(bot, f"Ticket delivery needs retry: order={order_id}, state={result}")


@router.callback_query(F.data.startswith("pay:phonepe:"))
async def pay_phonepe(cb: CallbackQuery):
    # Fail closed: this repository's PhonePe adapter is deliberately disabled.
    # Do not create a pending order or show a fake QR until merchant API verification is implemented.
    await cb.answer(
        "PhonePe payment abhi enable nahi hai. Filhaal Telegram Stars use karein.",
        show_alert=True,
    )
