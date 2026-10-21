import uuid
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from config import EVENT_NAME, EVENT_DATE, VENUE, TICKET_PRICE_INR, TICKET_PRICE_STARS
from db import db
router = Router()

@router.message(Command("cancel"))
async def cancel_cmd(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("Cancelled. Main menu par wapas aane ke liye /start bhejein.")

def home_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎟️ Book Ticket", callback_data="menu:buy")],
        [InlineKeyboardButton(text="🎫 My Tickets", callback_data="menu:myticket")],
        [InlineKeyboardButton(text="ℹ️ Help", callback_data="menu:help")]
    ])

@router.message(CommandStart())
async def start(msg: Message, state: FSMContext):
    await state.clear()
    u=msg.from_user
    await db().execute("""INSERT INTO users(telegram_id,username,first_name) VALUES($1,$2,$3)
      ON CONFLICT(telegram_id) DO UPDATE SET username=EXCLUDED.username, first_name=EXCLUDED.first_name""",
      u.id,u.username,u.first_name)
    await msg.answer(f"🎟️ <b>{EVENT_NAME}</b>\n📅 {EVENT_DATE}\n📍 {VENUE}\n\nINR ticket: ₹{TICKET_PRICE_INR}\nStars ticket: ⭐ {TICKET_PRICE_STARS}", reply_markup=home_kb())

@router.message(Command("help"))
async def help_cmd(msg: Message):
    await msg.answer("Use Book Ticket to purchase and My Tickets to view issued tickets.")

@router.callback_query(F.data == "menu:help")
async def help_button(cb: CallbackQuery):
    await cb.answer(); await cb.message.answer("For ticket/payment support, contact the event organiser.")

@router.callback_query(F.data == "menu:buy")
async def buy_menu(cb: CallbackQuery):
    await cb.answer()
    kb=InlineKeyboardMarkup(inline_keyboard=[
      [InlineKeyboardButton(text=f"Pay ₹{TICKET_PRICE_INR} with PhonePe", callback_data="pay:phonepe")],
      [InlineKeyboardButton(text=f"Pay ⭐ {TICKET_PRICE_STARS} Telegram Stars", callback_data="pay:stars")],
      [InlineKeyboardButton(text="⬅️ Back", callback_data="user:home")]])
    await cb.message.answer(f"Choose payment method for {EVENT_NAME}:", reply_markup=kb)

@router.callback_query(F.data == "user:home")
async def home(cb: CallbackQuery):
    await cb.answer(); await cb.message.answer("Main menu", reply_markup=home_kb())

@router.callback_query(F.data == "menu:myticket")
async def my_tickets(cb: CallbackQuery):
    await cb.answer()
    rows=await db().fetch("""SELECT t.ticket_code,t.delivered_at,t.checked_in_at,o.status
      FROM tickets t JOIN orders o USING(order_id) WHERE t.user_id=$1 ORDER BY t.created_at DESC LIMIT 10""",cb.from_user.id)
    if not rows: await cb.message.answer("Abhi aapke tickets nahi hain. Book Ticket se shuru karein."); return
    for r in rows:
        await cb.message.answer(f"🎟️ <code>{r['ticket_code']}</code>\nOrder: {r['status']}\nDelivered: {'Yes' if r['delivered_at'] else 'Pending'}\nChecked in: {'Yes' if r['checked_in_at'] else 'No'}")

@router.message(Command("myid"))
async def myid(msg: Message):
    await msg.answer(f"Your Telegram ID: <code>{msg.from_user.id}</code>")


@router.callback_query(F.data == "forcejoin:verify")
async def forcejoin_verify(cb: CallbackQuery):
    # The ForceJoinMiddleware runs before this handler and only lets it through when every
    # configured channel membership was verified.
    await cb.answer("✅ Membership verify ho gaya!", show_alert=True)
    await cb.message.answer("Ab bot use kar sakte hain. /start dabayein.")
