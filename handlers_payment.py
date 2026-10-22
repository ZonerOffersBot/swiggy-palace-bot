import uuid
import logging

from aiogram import Router, F, Bot\nfrom aiogram.fsm.context import FSMContext\nfrom aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, LabeledPrice, PreCheckoutQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db import db
from services_ticket import atomic_create_and_deliver
from utils import notify_admins

router = Router()\n\n\nclass PromoFSM(StatesGroup):\n    waiting_code = State()
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
    kb.button(text="🎁 Apply promo code", callback_data=f"promo:enter:{tier_id}")
    kb.button(text="Continue to payment", callback_data=f"pay:continue:{tier_id}")
    kb.button(text="⬅️ Back", callback_data="menu:buy")
    kb.adjust(1)
    await cb.message.edit_text(
        f"🎫 <b>{tier['label']}</b>\\nPrice: {_tier_price_label(tier['price_inr'])} / ⭐{tier['price_stars']}\\n\\n"
        "Agar admin ne free-ticket promo code diya hai to Apply promo code dabayein. "
        "Warna normal payment continue karein.",
        reply_markup=kb.as_markup(),
    )
    await cb.answer()


async def show_payment_methods(cb: CallbackQuery, tier_id: int):
    tier = await db().fetchrow("SELECT * FROM ticket_types WHERE id=$1 AND is_active=TRUE", tier_id)
    if not tier:
        await cb.answer("Ticket type ab available nahi hai.", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    kb.button(text=f"⭐ Telegram Stars ({tier['price_stars']})", callback_data=f"pay:stars:{tier_id}")
    kb.button(text="📱 UPI / PhonePe (temporarily unavailable)", callback_data=f"pay:phonepe:{tier_id}")
    kb.button(text="🎁 Apply promo code", callback_data=f"promo:enter:{tier_id}")
    kb.button(text="⬅️ Back", callback_data=f"tier:{tier_id}")
    kb.adjust(1)
    await cb.message.edit_text(f"🎫 <b>{tier['label']}</b>\\n\\nPayment method chunein:", reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("pay:continue:"))
async def continue_to_payment(cb: CallbackQuery):
    try:
        tier_id = int(cb.data.rsplit(":", 1)[1])
    except ValueError:
        await cb.answer("Ticket type invalid hai.", show_alert=True)
        return
    await show_payment_methods(cb, tier_id)


@router.callback_query(F.data.startswith("promo:enter:"))
async def promo_enter(cb: CallbackQuery, state: FSMContext):
    try:
        tier_id = int(cb.data.rsplit(":", 1)[1])
    except ValueError:
        await cb.answer("Ticket type invalid hai.", show_alert=True)
        return
    tier = await db().fetchrow("SELECT id,label FROM ticket_types WHERE id=$1 AND is_active=TRUE", tier_id)
    if not tier:
        await cb.answer("Ticket type ab available nahi hai.", show_alert=True)
        return
    await state.set_state(PromoFSM.waiting_code)
    await state.update_data(promo_tier_id=tier_id)
    await cb.answer()
    await cb.message.answer(f"🎁 <b>{tier['label']}</b> ke liye admin ka promo code bhejein.\\nValid code hua aur limit available hui to ticket free issue ho jayega.\\nCancel: /cancel")


@router.message(PromoFSM.waiting_code, F.text)
async def promo_redeem(msg: Message, state: FSMContext, bot: Bot):
    raw = (msg.text or "").strip()
    if raw.split(maxsplit=1)[0].split("@", 1)[0] == "/cancel":
        await state.clear()
        await msg.answer("Promo apply cancel ho gaya. /start se dobara shuru karein.")
        return
    code = raw.upper()
    data = await state.get_data()
    tier_id = int(data["promo_tier_id"])
    tier = await db().fetchrow("SELECT * FROM ticket_types WHERE id=$1 AND is_active=TRUE", tier_id)
    if not tier:
        await state.clear()
        await msg.answer("Yeh ticket type ab available nahi hai. /start se dobara try karein.")
        return
    order_id = uuid.uuid4()
    failure = None
    async with db().acquire() as conn:
        async with conn.transaction():
            promo = await conn.fetchrow("SELECT * FROM promo_codes WHERE code=$1 AND is_active=TRUE FOR UPDATE", code)
            if not promo:
                failure = "Yeh promo code valid nahi hai ya admin ne disable kar diya hai."
            elif promo["max_uses"] is not None and promo["uses_count"] >= promo["max_uses"]:
                failure = "Is promo code ki use limit khatam ho gayi hai."
            else:
                used = await conn.fetchval("SELECT EXISTS(SELECT 1 FROM promo_redemptions WHERE code=$1 AND user_id=$2)", code, msg.from_user.id)
                if used:
                    failure = "Aap yeh promo code pehle hi use kar chuke hain."
                else:
                    await conn.execute(
                        """INSERT INTO orders
                           (order_id,user_id,amount,currency,status,gateway,gateway_txn_id,idempotency_key,ticket_type_id,paid_at)
                           VALUES($1,$2,0,'INR','paid','promo',$3,$4,$5,NOW())""",
                        order_id, msg.from_user.id, f"PROMO:{code}:{order_id}", f"promo:{code}:{order_id}", tier_id
                    )
                    await conn.execute("INSERT INTO promo_redemptions(code,user_id,order_id) VALUES($1,$2,$3)", code, msg.from_user.id, order_id)
                    await conn.execute("UPDATE promo_codes SET uses_count=uses_count+1 WHERE code=$1", code)
    if failure:
        await msg.answer(f"❌ {failure}\\nCode dobara check karein ya admin se contact karein. /cancel se exit kar sakte hain.")
        return
    await state.clear()
    result = await atomic_create_and_deliver(bot, order_id)
    if result == "delivered":
        await msg.answer("✅ Promo code accepted! Aapka ticket free issue ho gaya. Ticket PDF yahin bhej diya hai.")
        await notify_admins(bot, f"🎁 Free ticket issued\\nCode: <code>{code}</code>\\nTicket: {tier['label']}\\nUser: <code>{msg.from_user.id}</code>\\nOrder: <code>{order_id}</code>")
    else:
        await msg.answer("✅ Promo code accepted. Ticket delivery pending hai; system retry karega. Agar PDF na aaye to support se contact karein.")
        await notify_admins(bot, f"⚠️ Promo accepted but ticket delivery state={result}\\nCode: {code}\\nUser: {msg.from_user.id}\\nOrder: {order_id}")


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
