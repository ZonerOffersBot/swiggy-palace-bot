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
    waiting_message = State()


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
    welcome = await get_setting(
        "welcome_msg",
        "Welcome! Check the event details and choose an option below to book your ticket.",
    )
    event = await get_setting("event_name", EVENT_NAME)
    date = await get_setting("event_date", EVENT_DATE)
    venue = await get_setting("venue", VENUE)
    tiers = await db().fetch(
        "SELECT label, price_inr, price_stars FROM ticket_types WHERE is_active=TRUE ORDER BY position,id"
    )
    lines = [f"• {row['label']} — ₹{row['price_inr'] / 100:.0f} or ⭐ {row['price_stars']}" for row in tiers]
    ticket_text = "\n".join(lines) if lines else "Tickets are not on sale right now. Please check back later."
    await msg.answer(
        f"{welcome}\n\n🎭 <b>{event}</b>\n📅 {date}\n📍 {venue}"
        f"\n\n<b>Available tickets</b>\n{ticket_text}"
        f"\n\nChoose an option below whenever you're ready.",
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
async def help_start(cb: CallbackQuery):
    rows = await db().fetch(
        "SELECT id,status,COALESCE(query,message,'') AS query,created_at FROM support_tickets WHERE user_id=$1 ORDER BY created_at DESC LIMIT 10",
        cb.from_user.id,
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ New Support Ticket", callback_data="support:new")
    for row in rows:
        label = f"#{row['id']} — {row['status']} — {row['query'][:22]}"
        kb.button(text=label, callback_data=f"support:open:{row['id']}")
    kb.button(text="⬅️ Main Menu", callback_data="user:home")
    kb.adjust(1)
    await cb.answer()
    await cb.message.answer(
        "🆘 <b>Support Centre</b>\nExisting ticket kholkar conversation continue karein, ya naya ticket banayein.",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data == "support:new")
async def support_new(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SupportFSM.waiting_query)
    await cb.answer()
    await cb.message.answer("🆘 Apni query bhejein (max 500 chars). Admin isi ticket mein reply karega. Cancel: /cancel")


@router.callback_query(F.data.startswith("support:open:"))
async def support_open(cb: CallbackQuery, state: FSMContext):
    try:
        ticket_id = int(cb.data.rsplit(":", 1)[1])
    except (ValueError, AttributeError):
        await cb.answer("Invalid ticket.", show_alert=True)
        return
    ticket = await db().fetchrow(
        "SELECT id,status,COALESCE(query,message,'') AS query FROM support_tickets WHERE id=$1 AND user_id=$2",
        ticket_id, cb.from_user.id,
    )
    if not ticket:
        await cb.answer("Ticket nahi mila.", show_alert=True)
        return
    messages = await db().fetch(
        "SELECT sender_role,message_text,created_at FROM support_messages WHERE ticket_id=$1 ORDER BY id ASC LIMIT 50",
        ticket_id,
    )
    text = f"🆘 <b>Support #{ticket_id}</b> — {ticket['status']}\n\n"
    if not messages:
        text += f"👤 You: {ticket['query']}\n"
    else:
        for row in messages[-20:]:
            who = "👤 You" if row["sender_role"] == "user" else "🛠 Admin"
            text += f"{who}: {row['message_text'][:700]}\n\n"
    kb = InlineKeyboardBuilder()
    if ticket["status"] == "open":
        kb.button(text="✍️ Reply to Admin", callback_data=f"support:reply:{ticket_id}")
    kb.button(text="🔄 Refresh Conversation", callback_data=f"support:open:{ticket_id}")
    kb.button(text="⬅️ Support Centre", callback_data="menu:help")
    kb.adjust(1)
    await state.clear()
    await cb.answer()
    await cb.message.answer(text[:3900], reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("support:reply:"))
async def support_reply_start(cb: CallbackQuery, state: FSMContext):
    try:
        ticket_id = int(cb.data.rsplit(":", 1)[1])
    except (ValueError, AttributeError):
        await cb.answer("Invalid ticket.", show_alert=True)
        return
    exists = await db().fetchval(
        "SELECT EXISTS(SELECT 1 FROM support_tickets WHERE id=$1 AND user_id=$2 AND status='open')",
        ticket_id, cb.from_user.id,
    )
    if not exists:
        await cb.answer("Ticket open nahi hai.", show_alert=True)
        return
    await state.set_state(SupportFSM.waiting_message)
    await state.update_data(support_ticket_id=ticket_id)
    await cb.answer()
    await cb.message.answer(f"Support #{ticket_id} mein apna message bhejein. Cancel: /cancel")


@router.message(SupportFSM.waiting_message, F.text)
async def support_user_message(msg: Message, state: FSMContext, bot: Bot):
    body = (msg.text or "").strip()
    if not body:
        await msg.answer("Message text bhejein.")
        return
    if body.split(maxsplit=1)[0].split("@",1)[0] == "/cancel":
        await state.clear()
        await msg.answer("Reply cancel ho gaya. Support Centre kholne ke liye /start dabayein.")
        return
    data = await state.get_data()
    ticket_id = data.get("support_ticket_id")
    ticket = await db().fetchrow(
        "SELECT id,status FROM support_tickets WHERE id=$1 AND user_id=$2",
        ticket_id, msg.from_user.id,
    )
    if not ticket or ticket["status"] != "open":
        await state.clear()
        await msg.answer("Yeh support ticket ab open nahi hai.")
        return
    body = body[:2000]
    await db().execute(
        "INSERT INTO support_messages(ticket_id,sender_id,sender_role,message_text) VALUES($1,$2,'user',$3)",
        ticket_id, msg.from_user.id, body,
    )
    await db().execute(
        "UPDATE support_tickets SET message=$1,query=$1 WHERE id=$2",
        body, ticket_id,
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="✍️ Reply", callback_data=f"sup:reply:{ticket_id}")
    kb.button(text="📂 Open Conversation", callback_data=f"sup:view:{ticket_id}")
    kb.button(text="🔒 Close", callback_data=f"sup:close:{ticket_id}")
    kb.adjust(1)
    user = msg.from_user
    for admin_id in await get_all_admin_ids():
        try:
            await bot.send_message(
                admin_id,
                f"📩 <b>Support #{ticket_id} — New user message</b>\n"
                f"👤 {user.full_name} (@{user.username or '—'})\n"
                f"🆔 <code>{user.id}</code>\n\n{body}",
                reply_markup=kb.as_markup(),
            )
        except Exception:
            log.exception("Could not notify admin %s about support message %s", admin_id, ticket_id)
    user_kb = InlineKeyboardBuilder()
    user_kb.button(text="📂 Open Conversation", callback_data=f"support:open:{ticket_id}")
    await msg.answer(
        f"✅ Message Support #{ticket_id} mein bhej diya. Admin ka reply isi conversation mein milega.",
        reply_markup=user_kb.as_markup(),
    )


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
    await db().execute(
        "INSERT INTO support_messages(ticket_id,sender_id,sender_role,message_text) VALUES($1,$2,'user',$3)",
        tid, user.id, text,
    )
    await state.clear()
    user_kb = InlineKeyboardBuilder()
    user_kb.button(text="📂 Open Conversation", callback_data=f"support:open:{tid}")
    user_kb.button(text="⬅️ Main Menu", callback_data="user:home")
    user_kb.adjust(1)
    await msg.answer(
        f"✅ Support ticket #{tid} create ho gaya. Admin ka reply isi conversation mein milega.",
        reply_markup=user_kb.as_markup(),
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="✍️ Reply", callback_data=f"sup:reply:{tid}")
    kb.button(text="📂 Open Conversation", callback_data=f"sup:view:{tid}")
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
