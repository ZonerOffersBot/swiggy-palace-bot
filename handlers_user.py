import logging
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardMarkup
from aiogram.types import InlineKeyboardButton
from config import EVENT_NAME, EVENT_DATE, VENUE, TICKET_PRICE_INR, TICKET_PRICE_STARS
from db import db
from utils import get_setting, get_all_admin_ids

log = logging.getLogger(__name__)
router = Router()


class SupportFSM(StatesGroup):
    waiting_query = State()


async def build_home_kb():
    rows = await db().fetch(
        "SELECT key, label FROM user_menu WHERE is_active=TRUE ORDER BY position"
    )
    kb = InlineKeyboardBuilder()
    for row in rows:
        kb.button(text=row["label"], callback_data=f"menu:{row['key']}")
    kb.adjust(1)
    return kb.as_markup()


@router.message(CommandStart())
async def start(msg: Message, state: FSMContext):
    await state.clear()
    user = msg.from_user
    await db().execute(
        """INSERT INTO users(telegram_id, username, first_name, full_name)
           VALUES($1,$2,$3,$4)
           ON CONFLICT(telegram_id) DO UPDATE SET
             username=EXCLUDED.username,
             first_name=EXCLUDED.first_name,
             full_name=EXCLUDED.full_name""",
        user.id, user.username, user.first_name, user.full_name,
    )
    welcome = await get_setting("welcome_msg", "Welcome!")
    event = await get_setting("event_name", EVENT_NAME)
    date = await get_setting("event_date", EVENT_DATE)
    venue = await get_setting("venue", VENUE)
    await msg.answer(
        f"{welcome}\n\n🎭 <b>{event}</b>\n📅 {date}\n📍 {venue}"
        f"\n\nINR ticket: ₹{TICKET_PRICE_INR}\nStars ticket: ⭐ {TICKET_PRICE_STARS}",
        reply_markup=await build_home_kb(),
    )


@router.message(Command("help"))
async def help_cmd(msg: Message):
    await msg.answer("Support ke liye menu mein 'Help / Support' button dabayein.")


@router.message(Command("myid"))
async def my_id(msg: Message):
    await msg.answer(f"🆔 Aapki ID: <code>{msg.from_user.id}</code>")


@router.message(Command("cancel"))
async def cancel(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("Cancelled. /start to restart.")


@router.callback_query(F.data == "user:home")
async def home(cb: CallbackQuery):
    await cb.answer()
    await cb.message.answer("Main menu:", reply_markup=await build_home_kb())


@router.callback_query(F.data == "menu:help")
async def help_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SupportFSM.waiting_query)
    await cb.answer()
    await cb.message.answer("🆘 Apni query likhein (max 500 chars). Cancel: /cancel")


@router.message(SupportFSM.waiting_query, F.text)
async def support_submit(msg: Message, state: FSMContext, bot: Bot):
    text = (msg.text or "").strip()[:500]
    if not text:
        await msg.answer("Kripya text bhejein.")
        return
    user = msg.from_user
    tid = await db().fetchval(
        """INSERT INTO support_tickets(user_id, username, full_name, message, query)
           VALUES($1,$2,$3,$4,$4) RETURNING id""",
        user.id, user.username, user.full_name, text,
    )
    await state.clear()
    await msg.answer(
        f"✅ Query #{tid} admin ko bhej di. Reply jald milega.",
        reply_markup=await build_home_kb(),
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="✍️ Reply", callback_data=f"sup:reply:{tid}")
    kb.button(text="🔒 Close", callback_data=f"sup:close:{tid}")
    kb.adjust(1)
    username = f"@{user.username}" if user.username else "(no username)"
    for admin_id in await get_all_admin_ids():
        try:
            await bot.send_message(
                admin_id,
                f"📩 <b>Support #{tid}</b>\n👤 {user.full_name} {username}"
                f"\n🆔 <code>{user.id}</code>\n\n{text}",
                reply_markup=kb.as_markup(),
            )
        except Exception:
            log.exception("Could not notify admin %s about support ticket %s", admin_id, tid)


@router.callback_query(F.data == "menu:buy")
async def buy_menu(cb: CallbackQuery):
    await cb.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Pay ₹{TICKET_PRICE_INR} with PhonePe", callback_data="pay:phonepe")],
        [InlineKeyboardButton(text=f"Pay ⭐ {TICKET_PRICE_STARS} Telegram Stars", callback_data="pay:stars")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="user:home")],
    ])
    await cb.message.answer(f"Choose payment method for {EVENT_NAME}:", reply_markup=kb)


@router.callback_query(F.data == "menu:myticket")
async def my_tickets(cb: CallbackQuery):
    rows = await db().fetch(
        """SELECT t.ticket_code, t.delivered_at, t.checked_in_at, o.status
           FROM tickets t JOIN orders o USING(order_id)
           WHERE t.user_id=$1 ORDER BY t.created_at DESC LIMIT 10""",
        cb.from_user.id,
    )
    if not rows:
        await cb.message.answer("Aapne abhi koi ticket nahi kharidi.")
    else:
        text = "🎟 <b>Aapki tickets:</b>\n\n"
        for row in rows:
            status = "✅ Used" if row["checked_in_at"] else "🟢 Valid"
            if row["status"] != "paid" or not row["delivered_at"]:
                status = "🟡 Pending"
            text += f"• <code>{row['ticket_code']}</code> — {status}\n"
        await cb.message.answer(text)
    await cb.answer()


@router.callback_query(F.data == "forcejoin:verify")
async def forcejoin_verify(cb: CallbackQuery):
    await cb.answer("Verify ho gaya! Ab bot use karein.", show_alert=True)
    await cb.message.answer("Ab bot use kar sakte hain. /start dabayein.")
