import logging
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardMarkup
from aiogram.types import InlineKeyboardButton
from config import EVENT_NAME, EVENT_DATE, VENUE, TICKET_PRICE_INR, TICKET_PRICE_STARS
from db import db
from menu_art import user_menu_photo
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
    # Clear any stale persistent reply keyboard left by an older bot version.
    await msg.answer("⌨️ Menu updated.", reply_markup=ReplyKeyboardRemove())
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
    await msg.answer_photo(
        photo=user_menu_photo(),
        caption=(
            f"{welcome}\n\n🎭 <b>{event}</b>\n📅 {date}\n📍 {venue}"
            f"\n\n<b>Available tickets</b>\n{ticket_text}"
            f"\n\nChoose an option below whenever you're ready."
        ),
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
    await cb.message.answer_photo(photo=user_menu_photo(), caption="Main menu:", reply_markup=await build_home_kb())


@router.callback_query(F.data == "menu:help")
async def help_start(cb: CallbackQuery):
    rows = await db().fetch(
        "SELECT id,status,COALESCE(query,message,'') AS query,created_at FROM support_tickets WHERE user_id=$1 ORDER BY created_at DESC LIMIT 10",
        cb.from_user.id,
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="📚 Frequently Asked Questions", callback_data="support:faq")
    kb.button(text="💬 Live Chat with Support", callback_data="support:new")
    for row in rows:
        label = f"#{row['id']} — {row['status']} — {row['query'][:22]}"
        kb.button(text=label, callback_data=f"support:open:{row['id']}")
    kb.button(text="⬅️ Main Menu", callback_data="user:home")
    kb.adjust(1)
    await cb.answer()
    await cb.message.answer(
        "🆘 <b>Support Centre</b>\nFAQ se quick answers paayein ya Live Chat se admin ko message bhejein. Admin reply isi conversation mein milega.",
        reply_markup=kb.as_markup(),
    )




@router.callback_query(F.data == "support:faq")
async def support_faq(cb: CallbackQuery):
    kb = InlineKeyboardBuilder()
    questions = [
        ("🧭 Bot kaise use karein?", "faq:howto"),
        ("🛒 JSON Shop load nahi ho raha", "faq:shop"),
        ("💰 Wallet balance kaise dekhein?", "faq:wallet"),
        ("➕ Wallet deposit pending", "faq:deposit"),
        ("💳 Payment deduct, order pending", "faq:payment"),
        ("📦 Purchase ke baad file nahi mili", "faq:delivery"),
        ("📂 File download/open nahi ho rahi", "faq:file"),
        ("🔁 Galat ya duplicate purchase", "faq:duplicate"),
        ("🎟 Ticket / order status", "faq:ticket"),
        ("🔐 Force-join verify nahi ho raha", "faq:join"),
        ("↩️ Refund / cancellation query", "faq:refund"),
        ("💬 Live Chat with Support", "support:new"),
        ("⬅️ Support Centre", "menu:help"),
    ]
    for label, key in questions:
        kb.button(text=label, callback_data=key)
    kb.adjust(1)
    await cb.answer()
    await cb.message.answer("📚 <b>Help & FAQs</b>\nNeeche apna sawal select karein. Har jawab ke baad zarurat ho to Live Chat par support team ko message bhej sakte hain.", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("faq:"))
async def support_faq_answer(cb: CallbackQuery):
    answers = {
        "faq:howto": "🧭 <b>Bot kaise use karein?</b>\n/start bhejkar main menu kholein. Buttons se Shop, Wallet, My Purchases aur Help / Support select karein. Kisi option par response na aaye to button dobara tap karke Live Chat par report karein.",
        "faq:shop": "🛒 <b>JSON Shop load nahi ho raha</b>\n1) Bot ko /start bhejein. 2) JSON Shop ko dobara open karein. 3) Thodi der baad Refresh karke dekhein. Agar 'unavailable' ya blank screen phir bhi aaye, screenshot aur approximate time ke saath Live Chat par report karein.",
        "faq:wallet": "💰 <b>Wallet balance kaise dekhein?</b>\nMain menu mein Wallet kholein. Balance aur available wallet actions wahin dikhte hain. Purane credits/debits verify karne ke liye Transaction History check karein.",
        "faq:deposit": "➕ <b>Wallet deposit pending</b>\nPayment ka UTR / transaction reference aur receipt sambhal kar rakhein. Transaction History check karein aur status update hone ke liye kuch waqt dein. Amount debit ho gaya lekin wallet credit nahi hua, to Live Chat par UTR, amount aur payment time bhejein. Verify hone se pehle same deposit repeat na karein.",
        "faq:payment": "💳 <b>Payment deduct hua, order pending hai</b>\nDobara payment turant na karein. Transaction / order history check karein. Live Chat par order ID, UTR/reference, amount aur payment time bhejein. Support team payment status verify kar sakegi.",
        "faq:delivery": "📦 <b>Purchase ke baad file nahi mili</b>\nMy Purchases kholkar order status aur delivery details check karein. Agar order paid/complete hai lekin file nahi dikhti, order ID ke saath Live Chat par message bhejein.",
        "faq:file": "📂 <b>File download ya open nahi ho rahi</b>\nFile ko dobara download karein, device mein free storage check karein aur supported app se open karein. Agar file corrupt, password-protected ya missing lagti hai, file ka naam aur order ID Live Chat par bhejein. Apna password ya OTP share na karein.",
        "faq:duplicate": "🔁 <b>Galat ya duplicate purchase</b>\nMy Purchases mein dono order entries check karein. Dono order IDs, item name aur payment references Live Chat par bhejein. Support team records check karegi; refund ya reversal eligibility review ke baad hi confirm hogi.",
        "faq:ticket": "🎟 <b>Ticket / order status</b>\nMy Tickets ya My Purchases mein latest status dekhein. Pending ya missing ticket ke liye order ID / ticket code aur payment reference Live Chat par bhejein. Ticket code ko public group mein share na karein.",
        "faq:join": "🔐 <b>Force-join verify nahi ho raha</b>\nRequired channel(s) ko join karein, Telegram mein membership confirm hone dein, phir bot par Verify button dobara tap karein. Agar issue rahe to channel ka naam aur screenshot Live Chat par bhejein.",
        "faq:refund": "↩️ <b>Refund / cancellation</b>\nRefund aur cancellation order type aur applicable policy par depend karte hain; automatic approval guaranteed nahi hai. Order ID, reason aur payment reference Live Chat par bhejein. Support team eligibility check karke update degi.",
    }
    answer = answers.get(cb.data)
    if not answer:
        await cb.answer("FAQ nahi mila.", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="💬 Live Chat with Support", callback_data="support:new")
    kb.button(text="📚 All FAQs", callback_data="support:faq")
    kb.button(text="⬅️ Support Centre", callback_data="menu:help")
    kb.adjust(1)
    await cb.answer()
    await cb.message.answer(answer, reply_markup=kb.as_markup())

@router.callback_query(F.data == "support:new")
async def support_new(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SupportFSM.waiting_query)
    await cb.answer()
    await cb.message.answer("💬 <b>Live Chat</b>\nApni problem detail mein bhejein (max 500 characters). Aapka message support team ko turant forward hoga; reply isi chat thread mein milega. Cancel: /cancel")


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
