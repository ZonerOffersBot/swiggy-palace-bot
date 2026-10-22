import logging
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from config import EVENT_NAME
from db import db
from utils import is_admin
log = logging.getLogger(__name__)
router=Router()

def admin_keyboard():
    kb = InlineKeyboardBuilder()
    buttons = [
        ("📊 Stats", "admin:stats"), ("🎟 Ticket Types", "admin:tiers"),
        ("📁 Ticket Files", "admin:files"), ("⚙️ Settings", "admin:settings"),
        ("🧭 User Menu", "admin:menu"), ("📢 Force Join", "admin:force"),
        ("👮 Admins", "admin:admins"), ("🆘 Support", "admin:support"),
        ("🔄 Refresh", "admin:home"),
    ]
    for label, data in buttons:
        kb.button(text=label, callback_data=data)
    kb.adjust(2, 2, 2, 2, 1)
    return kb.as_markup()


async def admin_home_text():
    users = await db().fetchval("SELECT COUNT(*) FROM users")
    orders = await db().fetchval("SELECT COUNT(*) FROM orders")
    paid = await db().fetchval("SELECT COUNT(*) FROM orders WHERE status='paid'")
    tickets = await db().fetchval("SELECT COUNT(*) FROM tickets")
    return (f"🛠️ <b>{EVENT_NAME} Admin Panel</b>\n\n"
            f"👥 Users: {users}\n🧾 Orders: {orders}\n"
            f"✅ Paid orders: {paid}\n🎟 Tickets issued: {tickets}\n\n"
            "Neeche kisi section ko select karein.")


@router.message(Command("admin"))
async def admin_panel(msg: Message):
    if not await is_admin(msg.from_user.id):
        await msg.answer(
            "⛔ Admin access nahi hai.\n"
            f"Aapki Telegram ID: <code>{msg.from_user.id}</code>\n\n"
            "Render → Environment mein ADMIN_IDS ke andar ye ID add karein "
            "(multiple admins ke liye comma-separated IDs), phir service redeploy/restart karein."
        )
        return
    try:
        await msg.answer(await admin_home_text(), reply_markup=admin_keyboard())
    except Exception:
        log.exception("Admin panel failed for user %s", msg.from_user.id)
        await msg.answer("⚠️ Admin panel database error. Render Logs mein /admin ke baad wali traceback check karein.")


@router.callback_query(F.data.in_({"admin:home", "admin:stats", "admin:tiers", "admin:files", "admin:settings", "admin:menu", "admin:force", "admin:admins", "admin:support"}))
async def admin_navigation(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    section = cb.data.split(":", 1)[1]
    section_markup = admin_keyboard()
    try:
        if section in ("home", "stats"):
            text = await admin_home_text()
        elif section == "tiers":
            rows = await db().fetch("SELECT id,label,price_inr,price_stars,is_active FROM ticket_types ORDER BY position,id")
            text = "🎟 <b>Ticket Types</b>\n" + ("\n".join(f"• {r['label']} — ₹{r['price_inr']/100:.2f} / ⭐ {r['price_stars']} — {'Active' if r['is_active'] else 'Inactive'} (ID {r['id']})" for r in rows) or "Abhi koi ticket type nahi hai.")
            kb = InlineKeyboardBuilder()
            for r in rows:
                kb.button(text=f"✏️ Edit {r['label'][:24]}", callback_data=f"admin:edit_tier:{r['id']}")
                kb.button(text=f"📎 Add file: {r['label'][:18]}", callback_data=f"admin:add_file:{r['id']}")
            kb.button(text="⬅️ Admin home", callback_data="admin:home")
            kb.adjust(1)
            section_markup = kb.as_markup()
        elif section == "files":
            rows = await db().fetch("SELECT f.id,t.label,f.file_type,f.is_active FROM ticket_files f JOIN ticket_types t ON t.id=f.ticket_type_id ORDER BY f.position,f.id LIMIT 30")
            text = "📁 <b>Ticket Files (latest 30)</b>\n" + ("\n".join(f"• #{r['id']} — {r['label']} — {r['file_type']} — {'Active' if r['is_active'] else 'Inactive'}" for r in rows) or "Abhi koi ticket file add nahi hai.")
            kb = InlineKeyboardBuilder()
            tiers = await db().fetch("SELECT id,label FROM ticket_types ORDER BY position,id")
            for r in tiers:
                kb.button(text=f"➕ Add file: {r['label'][:28]}", callback_data=f"admin:add_file:{r['id']}")
            kb.button(text="⬅️ Admin home", callback_data="admin:home")
            kb.adjust(1)
            section_markup = kb.as_markup()
        elif section == "settings":
            rows = await db().fetch("SELECT key,value FROM bot_settings ORDER BY key")
            text = "⚙️ <b>Settings</b>\n" + ("\n".join(f"• <code>{r['key']}</code>: {r['value'][:150]}" for r in rows) or "Custom settings abhi set nahi hain.") + "\nEvent details yahin se edit kar sakte hain."
            kb = InlineKeyboardBuilder()
            for key, label in (("event_name","Event name"),("event_date","Event date"),("venue","Venue"),("welcome_msg","Welcome message")):
                kb.button(text=f"✏️ {label}", callback_data=f"admin:edit_setting:{key}")
            kb.button(text="⬅️ Admin home", callback_data="admin:home")
            kb.adjust(2,2,1)
            section_markup = kb.as_markup()
        elif section == "menu":
            rows = await db().fetch("SELECT key,label,is_active,position FROM user_menu ORDER BY position,key")
            text = "🧭 <b>User Menu</b>\nButton ka naam badalne ke liye Rename, aur dikhana/chhupana badalne ke liye Show/Hide dabayein. Button ka action fixed rahega.\n\n" + ("\n".join(f"• {r['position']}. {r['label']} — <code>{r['key']}</code> — {'Visible' if r['is_active'] else 'Hidden'}" for r in rows) or "User menu empty hai.")
            kb = InlineKeyboardBuilder()
            for r in rows:
                kb.button(text=f"✏️ Rename: {r['label'][:20]}", callback_data=f"admin:edit_menu:{r['key']}")
                action = "disable" if r["is_active"] else "enable"
                label = "🙈 Hide" if r["is_active"] else "👁 Show"
                kb.button(text=label, callback_data=f"admin:{action}_menu:{r['key']}")
            kb.button(text="⬅️ Admin home", callback_data="admin:home")
            kb.adjust(2, 2, 2, 1)
            section_markup = kb.as_markup()
        elif section == "force":
            rows = await db().fetch("SELECT channel_id,channel_username,invite_link,is_active FROM force_channels ORDER BY id")
            text = "📢 <b>Force Join Channels</b>\n" + ("\n".join(f"• {r['channel_username'] or r['channel_id']} — {'Active' if r['is_active'] else 'Inactive'}" for r in rows) or "Koi force-join channel configured nahi hai.")
            kb = InlineKeyboardBuilder()
            kb.button(text="➕ Add channel", callback_data="admin:add_force")
            for r in rows:
                action = "disable" if r['is_active'] else "enable"
                label = "⏸ Disable" if r['is_active'] else "▶️ Enable"
                kb.button(text=f"{label} {str(r['channel_username'] or r['channel_id'])[:24]}", callback_data=f"admin:{action}_force:{r['channel_id']}")
            kb.button(text="⬅️ Admin home", callback_data="admin:home")
            kb.adjust(1)
            section_markup = kb.as_markup()
        elif section == "admins":
            rows = await db().fetch("SELECT telegram_id,is_active FROM admins ORDER BY telegram_id")
            text = "👮 <b>Database Admins</b>\n" + ("\n".join(f"• <code>{r['telegram_id']}</code> — {'Active' if r['is_active'] else 'Inactive'}" for r in rows) or "Database admins list empty hai. Render ADMIN_IDS admins ko bhi access deta hai.")
            kb = InlineKeyboardBuilder()
            kb.button(text="➕ Add admin", callback_data="admin:add_admin")
            kb.button(text="➖ Remove admin", callback_data="admin:remove_admin")
            kb.button(text="⬅️ Admin home", callback_data="admin:home")
            kb.adjust(2,1)
            section_markup = kb.as_markup()
        elif section == "support":
            rows = await db().fetch("SELECT id,user_id,COALESCE(full_name,'') AS full_name,COALESCE(query,message,'') AS query,status,created_at FROM support_tickets ORDER BY created_at DESC LIMIT 15")
            text = "🆘 <b>Recent Support Tickets</b>\n" + ("\n\n".join(f"#{r['id']} — {r['full_name'] or r['user_id']} — {r['status']}\n{r['query'][:250]}" for r in rows) or "Abhi support tickets nahi hain.")
        else:
            text = "Unknown admin section."
        await cb.answer()
        if cb.message:
            await cb.message.answer(text, reply_markup=section_markup)
    except Exception:
        log.exception("Admin section %s failed for user %s", section, cb.from_user.id)
        await cb.answer("Section load nahi hua. Render Logs check karein.", show_alert=True)



@router.callback_query(F.data.startswith(("admin:disable_force:", "admin:enable_force:")))
async def toggle_force_channel(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    action, raw_id = cb.data.rsplit(":", 1)
    try:
        channel_id = int(raw_id)
    except ValueError:
        await cb.answer("Invalid channel ID.", show_alert=True)
        return
    active = action == "admin:enable_force"
    await db().execute("UPDATE force_channels SET is_active=$1 WHERE channel_id=$2", active, channel_id)
    await cb.answer("Channel enabled." if active else "Channel disabled.")
    if cb.message:
        await cb.message.answer("Channel status update ho gaya. Force Join section dobara kholkar check karein.", reply_markup=admin_keyboard())


@router.message(Command("checkin", "check"))
async def checkin(msg: Message):
    if not await is_admin(msg.from_user.id): return
    parts=(msg.text or "").split(maxsplit=1)
    if len(parts)!=2:
        await msg.answer("Usage: /checkin EVT-XXXXXXXXXX"); return
    code=parts[1].strip()
    async with db().acquire() as conn:
        async with conn.transaction():
            row=await conn.fetchrow("""SELECT t.*,o.status FROM tickets t JOIN orders o USING(order_id)
                WHERE t.ticket_code=$1 FOR UPDATE OF t""",code)
            if not row or row["status"]!="paid" or not row["delivered_at"]:
                await msg.answer("Ticket invalid hai ya payment/delivery confirm nahi hai."); return
            if row["checked_in_at"]:
                await msg.answer("Ticket pehle hi check-in ho chuka hai."); return
            await conn.execute("UPDATE tickets SET checked_in_at=NOW(),checked_in_by=$1,is_checked_in=TRUE WHERE ticket_id=$2",msg.from_user.id,row["ticket_id"])
    await msg.answer(f"✅ Check-in successful: <code>{code}</code>")

@router.message(Command("info"))
async def ticket_info(msg: Message):
    if not await is_admin(msg.from_user.id):
        return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await msg.answer("Usage: /info EVT-XXXXXXXXXX")
        return
    code = parts[1].strip().upper()
    row = await db().fetchrow(
        """SELECT t.ticket_code, t.user_id, t.created_at, t.delivered_at, t.checked_in_at,
                  o.status, o.amount, o.currency
           FROM tickets t JOIN orders o USING(order_id) WHERE t.ticket_code=$1""", code
    )
    if not row:
        await msg.answer("❌ Ticket nahi mila.")
        return
    status = "🔴 USED" if row["checked_in_at"] else ("🟢 VALID" if row["status"] == "paid" and row["delivered_at"] else "🟡 PENDING")
    await msg.answer(
        f"🎟 <b>Ticket Info</b>\nCode: <code>{row['ticket_code']}</code>\nStatus: {status}"
        f"\nPayment: {row['status']}\nAmount: {row['amount']} {row['currency']}"
        f"\nUser: <code>{row['user_id']}</code>\nIssued: {row['created_at']}"
        f"\nChecked in: {row['checked_in_at'] or '—'}"
    )


class SupportReplyFSM(StatesGroup):
    waiting_reply = State()


@router.callback_query(F.data.startswith("sup:reply:"))
async def support_reply_start(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    try:
        ticket_id = int(cb.data.rsplit(":", 1)[1])
    except (ValueError, AttributeError):
        await cb.answer("Invalid support ticket.", show_alert=True)
        return
    row = await db().fetchrow(
        "SELECT id, status FROM support_tickets WHERE id=$1", ticket_id
    )
    if not row or row["status"] != "open":
        await cb.answer("Ticket missing or already closed.", show_alert=True)
        return
    await state.set_state(SupportReplyFSM.waiting_reply)
    await state.update_data(support_ticket_id=ticket_id)
    await cb.answer()
    await cb.message.answer(f"Support #{ticket_id} ka reply bhejein. Cancel: /cancel")


@router.message(SupportReplyFSM.waiting_reply)
async def support_reply_send(msg: Message, state: FSMContext, bot: Bot):
    if not await is_admin(msg.from_user.id):
        await state.clear()
        return
    if (msg.text or "").strip().split(maxsplit=1)[0].split("@", 1)[0] == "/cancel":
        await state.clear()
        await msg.answer("Reply cancelled.")
        return
    reply_text = (msg.text or "").strip()[:2000]
    if not reply_text:
        await msg.answer("Text reply bhejein. Cancel: /cancel")
        return
    data = await state.get_data()
    ticket_id = data.get("support_ticket_id")
    row = await db().fetchrow(
        "SELECT user_id, status FROM support_tickets WHERE id=$1", ticket_id
    )
    if not row or row["status"] != "open":
        await state.clear()
        await msg.answer("Support ticket open nahi hai.")
        return
    await db().execute(
        "UPDATE support_tickets SET admin_reply=$1 WHERE id=$2 AND status='open'",
        reply_text, ticket_id
    )
    try:
        await bot.send_message(
            row["user_id"],
            f"💬 <b>Support reply #{ticket_id}</b>\n\n{reply_text}"
        )
    except Exception:
        log.exception("Failed to deliver support reply for ticket %s", ticket_id)
        await msg.answer("Reply database mein save hua, lekin user ko message deliver nahi hua.")
        await state.clear()
        return
    await state.clear()
    await msg.answer(f"✅ Support #{ticket_id} ka reply bhej diya.")


@router.callback_query(F.data.startswith("sup:close:"))
async def support_close(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    try:
        ticket_id = int(cb.data.rsplit(":", 1)[1])
    except (ValueError, AttributeError):
        await cb.answer("Invalid support ticket.", show_alert=True)
        return
    updated = await db().fetchval(
        "UPDATE support_tickets SET status='closed' WHERE id=$1 AND status='open' RETURNING id",
        ticket_id,
    )
    if updated:
        await cb.answer("Support ticket closed.")
        await cb.message.answer(f"🔒 Support #{ticket_id} closed by admin.")
    else:
        await cb.answer("Ticket missing or already closed.", show_alert=True)


class AdminEditFSM(StatesGroup):
    edit_tier = State()
    edit_setting = State()
    edit_menu = State()
    add_admin = State()
    remove_admin = State()
    add_force = State()
    add_file = State()


@router.callback_query(F.data.startswith("admin:edit_tier:"))
async def edit_tier_start(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True); return
    tier_id = int(cb.data.rsplit(":", 1)[1])
    row = await db().fetchrow("SELECT * FROM ticket_types WHERE id=$1", tier_id)
    if not row:
        await cb.answer("Ticket type nahi mila.", show_alert=True); return
    await state.set_state(AdminEditFSM.edit_tier)
    await state.update_data(tier_id=tier_id)
    await cb.answer()
    await cb.message.answer(
        f"🎟 <b>{row['label']}</b> edit karne ke liye ek line bhejein:\n"
        "<code>Name | INR rupees | Stars | yes/no</code>\n"
        "Example: General Ticket | 599 | 60 | yes\n"
        "Cancel: /cancel"
    )


@router.message(AdminEditFSM.edit_tier, F.text)
async def edit_tier_save(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id): await state.clear(); return
    if (msg.text or "").strip().split(maxsplit=1)[0].split("@",1)[0] == "/cancel":
        await state.clear(); await msg.answer("Edit cancelled."); return
    parts=[p.strip() for p in (msg.text or "").split("|")]
    if len(parts)!=4 or not parts[0] or not parts[1].isdigit() or not parts[2].isdigit() or parts[3].lower() not in ("yes","no","true","false","on","off"):
        await msg.answer("Format galat hai. Use: Name | INR rupees | Stars | yes/no"); return
    inr, stars=int(parts[1]),int(parts[2])
    if inr<1 or stars<1:
        await msg.answer("Price 0 se zyada hona chahiye."); return
    data=await state.get_data()
    await db().execute("UPDATE ticket_types SET label=$1,price_inr=$2,price_stars=$3,is_active=$4,updated_at=NOW() WHERE id=$5",
        parts[0][:100],inr*100,stars,parts[3].lower() in ("yes","true","on"),data["tier_id"])
    await state.clear()
    await msg.answer(f"✅ Ticket update ho gaya: {parts[0]} — ₹{inr} / ⭐{stars}. /admin kholkar Ticket Types refresh karein.")


@router.callback_query(F.data.startswith("admin:edit_setting:"))
async def edit_setting_start(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id): await cb.answer("Admin only.",show_alert=True); return
    key=cb.data.rsplit(":",1)[1]
    allowed={"event_name":"Event name","event_date":"Event date","venue":"Venue","welcome_msg":"Welcome message"}
    if key not in allowed: await cb.answer("Setting allowed nahi hai.",show_alert=True); return
    await state.set_state(AdminEditFSM.edit_setting); await state.update_data(setting_key=key)
    await cb.answer()
    await cb.message.answer(f"✏️ {allowed[key]} ka naya value bhejein (max 500 characters). Cancel: /cancel")


@router.message(AdminEditFSM.edit_setting, F.text)
async def edit_setting_save(msg: Message,state:FSMContext):
    if not await is_admin(msg.from_user.id): await state.clear(); return
    if (msg.text or "").strip().split(maxsplit=1)[0].split("@",1)[0] == "/cancel":
        await state.clear(); await msg.answer("Edit cancelled."); return
    value=(msg.text or "").strip()
    if not value or value.startswith("/cancel"): await state.clear(); await msg.answer("Cancelled."); return
    data=await state.get_data()
    await db().execute("INSERT INTO bot_settings(key,value,updated_at) VALUES($1,$2,NOW()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=NOW()",data["setting_key"],value[:500])
    await state.clear(); await msg.answer("✅ Setting save ho gayi. /admin se verify karein.")


@router.callback_query(F.data.startswith("admin:edit_menu:"))
async def edit_menu_start(cb:CallbackQuery,state:FSMContext):
    if not await is_admin(cb.from_user.id): await cb.answer("Admin only.",show_alert=True); return
    key=cb.data.rsplit(":",1)[1]
    row=await db().fetchrow("SELECT * FROM user_menu WHERE key=$1",key)
    if not row: await cb.answer("Menu item nahi mila.",show_alert=True); return
    await state.set_state(AdminEditFSM.edit_menu); await state.update_data(menu_key=key)
    await cb.answer()
    await cb.message.answer(f"✏️ Current button name: <b>{row['label']}</b>\nSirf naya button name bhejein (max 50 characters).\nIs button ka action change nahi hoga; sirf naam badlega.\nCancel: /cancel")


@router.message(AdminEditFSM.edit_menu,F.text)
async def edit_menu_save(msg:Message,state:FSMContext):
    if not await is_admin(msg.from_user.id): await state.clear(); return
    if (msg.text or "").strip().split(maxsplit=1)[0].split("@",1)[0] == "/cancel":
        await state.clear(); await msg.answer("Edit cancelled."); return
    label=(msg.text or "").strip()
    if not label or len(label)>50:
        await msg.answer("Button name 1–50 characters ka bhejein. Cancel: /cancel"); return
    d=await state.get_data()
    await db().execute("UPDATE user_menu SET label=$1 WHERE key=$2",label,d["menu_key"])
    await state.clear()
    await msg.answer(f"✅ Button ka naam update ho gaya: <b>{label}</b>\nUser ko naya menu dikhane ke liye /start dobara chalayein. Action pehle jaisa hi rahega.")


@router.callback_query(F.data.startswith(("admin:disable_menu:", "admin:enable_menu:")))
async def toggle_menu_item(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    action, key = cb.data.rsplit(":", 1)
    active = action == "admin:enable_menu"
    updated = await db().fetchval(
        "UPDATE user_menu SET is_active=$1 WHERE key=$2 RETURNING key",
        active, key
    )
    if not updated:
        await cb.answer("Menu item nahi mila.", show_alert=True)
        return
    await cb.answer("Menu item visible." if active else "Menu item hidden.")
    if cb.message:
        await cb.message.answer(
            "✅ Menu visibility update ho gayi. User ko updated menu dikhane ke liye /start dobara chalayein.",
            reply_markup=admin_keyboard()
        )


@router.callback_query(F.data == "admin:add_admin")
async def add_admin_start(cb:CallbackQuery,state:FSMContext):
    if not await is_admin(cb.from_user.id): await cb.answer("Admin only.",show_alert=True); return
    await state.set_state(AdminEditFSM.add_admin); await cb.answer()
    await cb.message.answer("Naye admin ka numeric Telegram user ID bhejein. Cancel: /cancel")


@router.message(AdminEditFSM.add_admin,F.text)
async def add_admin_save(msg:Message,state:FSMContext):
    if not await is_admin(msg.from_user.id): await state.clear(); return
    raw=(msg.text or "").strip()
    if raw=="/cancel": await state.clear(); await msg.answer("Cancelled."); return
    if not raw.isdigit(): await msg.answer("Sirf numeric Telegram ID bhejein."); return
    uid=int(raw)
    await db().execute("INSERT INTO admins(telegram_id,added_by,is_active) VALUES($1,$2,TRUE) ON CONFLICT(telegram_id) DO UPDATE SET is_active=TRUE,added_by=EXCLUDED.added_by",uid,msg.from_user.id)
    await state.clear(); await msg.answer(f"✅ Admin {uid} add/activate ho gaya.")


@router.callback_query(F.data == "admin:remove_admin")
async def remove_admin_start(cb:CallbackQuery,state:FSMContext):
    if not await is_admin(cb.from_user.id): await cb.answer("Admin only.",show_alert=True); return
    await state.set_state(AdminEditFSM.remove_admin); await cb.answer()
    await cb.message.answer("Remove karne ke liye database admin ka numeric Telegram ID bhejein. Render ADMIN_IDS se added admin ko yahan se remove nahi kar sakte.")


@router.message(AdminEditFSM.remove_admin,F.text)
async def remove_admin_save(msg:Message,state:FSMContext):
    if not await is_admin(msg.from_user.id): await state.clear(); return
    raw=(msg.text or "").strip()
    if raw=="/cancel": await state.clear(); await msg.answer("Cancelled."); return
    if not raw.isdigit(): await msg.answer("Sirf numeric Telegram ID bhejein."); return
    uid=int(raw)
    from config import ADMIN_IDS
    if uid in ADMIN_IDS:
        await msg.answer("Yeh ID Render ADMIN_IDS mein hai. Wahan se remove karke redeploy karna hoga."); await state.clear(); return
    await db().execute("UPDATE admins SET is_active=FALSE WHERE telegram_id=$1",uid)
    await state.clear(); await msg.answer(f"✅ Admin {uid} inactive kar diya.")


@router.callback_query(F.data == "admin:add_force")
async def add_force_start(cb:CallbackQuery,state:FSMContext):
    if not await is_admin(cb.from_user.id): await cb.answer("Admin only.",show_alert=True); return
    await state.set_state(AdminEditFSM.add_force); await cb.answer()
    await cb.message.answer("Channel details bhejein:\n<code>numeric_channel_id | @username | invite_link</code>\nExample: -1001234567890 | @mychannel | https://t.me/mychannel\nBot ko channel mein admin hona chahiye.")


@router.message(AdminEditFSM.add_force,F.text)
async def add_force_save(msg:Message,state:FSMContext):
    if not await is_admin(msg.from_user.id): await state.clear(); return
    p=[x.strip() for x in (msg.text or "").split("|")]
    if len(p)!=3 or not p[0].lstrip("-").isdigit():
        await msg.answer("Format: numeric_channel_id | @username | invite_link"); return
    channel_id=int(p[0]); username=p[1].lstrip("@") or None; invite=p[2] or None
    await db().execute("INSERT INTO force_channels(channel_id,channel_username,invite_link,is_active,added_by) VALUES($1,$2,$3,TRUE,$4) ON CONFLICT(channel_id) DO UPDATE SET channel_username=EXCLUDED.channel_username,invite_link=EXCLUDED.invite_link,is_active=TRUE,added_by=EXCLUDED.added_by",channel_id,username,invite,msg.from_user.id)
    await state.clear(); await msg.answer("✅ Force-join channel save ho gaya. Bot ka membership check karne ke liye bot ko channel admin rakhein.")


@router.callback_query(F.data.startswith("admin:add_file:"))
async def add_file_start(cb:CallbackQuery,state:FSMContext):
    if not await is_admin(cb.from_user.id): await cb.answer("Admin only.",show_alert=True); return
    tier_id=int(cb.data.rsplit(":",1)[1])
    tier=await db().fetchrow("SELECT id,label FROM ticket_types WHERE id=$1",tier_id)
    if not tier: await cb.answer("Ticket type nahi mila.",show_alert=True); return
    await state.set_state(AdminEditFSM.add_file); await state.update_data(file_tier_id=tier_id)
    await cb.answer()
    await cb.message.answer(f"📁 {tier['label']} ke liye ab document/photo ya text message bhejein. Cancel: /cancel")


@router.message(AdminEditFSM.add_file)
async def add_file_save(msg:Message,state:FSMContext,bot:Bot):
    if not await is_admin(msg.from_user.id): await state.clear(); return
    if msg.text and msg.text.strip()=="/cancel": await state.clear(); await msg.answer("Cancelled."); return
    data=await state.get_data(); tier_id=data["file_tier_id"]
    if msg.document:
        file_type="document"; file_id=msg.document.file_id; text_content=None; file_name=msg.document.file_name; mime=msg.document.mime_type; size=msg.document.file_size; caption=msg.caption
    elif msg.photo:
        file_type="photo"; file_id=msg.photo[-1].file_id; text_content=None; file_name=None; mime="image/jpeg"; size=msg.photo[-1].file_size; caption=msg.caption
    elif msg.text:
        file_type="text"; file_id=None; text_content=msg.text[:4000]; file_name=None; mime=None; size=None; caption=None
    else:
        await msg.answer("Document, photo ya text bhejein."); return
    await db().execute("INSERT INTO ticket_files(ticket_type_id,file_type,telegram_file_id,file_id,text_content,is_active,added_by,file_name,mime_type,file_size,caption) VALUES($1,$2,$3,$3,$4,TRUE,$5,$6,$7,$8,$9)",tier_id,file_type,file_id,text_content,msg.from_user.id,file_name,mime,size,caption)
    await state.clear(); await msg.answer("✅ File/content save ho gaya. Note: delivery flow mein ise use karne ka support alag se verify karna hoga.")
