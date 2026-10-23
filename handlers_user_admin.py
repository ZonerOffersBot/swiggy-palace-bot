import logging
import uuid
import json
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import MAIN_ADMIN_ID
from db import db
from utils import is_admin

router = Router()
log = logging.getLogger(__name__)


def is_main_admin(user_id: int) -> bool:
    return bool(MAIN_ADMIN_ID and int(user_id) == int(MAIN_ADMIN_ID))


class UserAdminFSM(StatesGroup):
    search = State()
    blacklist_reason = State()
    wallet_amount = State()


def user_admin_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔎 Search User", callback_data="admin:users_search")
    kb.button(text="🚫 Blacklisted Users", callback_data="admin:users_blacklisted")
    kb.button(text="📋 All Wallets", callback_data="admin:users_wallets")
    kb.button(text="🧾 Wallet Transactions", callback_data="admin:users_transactions")
    kb.button(text="⬅️ Admin Home", callback_data="admin:home")
    kb.adjust(1)
    return kb.as_markup()


async def show_user(cb: CallbackQuery, user_id: int):
    row = await db().fetchrow(
        """SELECT u.telegram_id,u.username,COALESCE(u.full_name,u.first_name,'') AS full_name,
                  COALESCE(w.balance_paise,0) AS balance_paise,
                  EXISTS(SELECT 1 FROM user_blacklist b WHERE b.user_id=u.telegram_id) AS is_blacklisted
           FROM users u LEFT JOIN wallets w ON w.user_id=u.telegram_id
           WHERE u.telegram_id=$1""",
        user_id,
    )
    if not row:
        await cb.answer("User nahi mila. User ko pehle bot start karna hoga.", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    if row["is_blacklisted"]:
        kb.button(text="✅ Remove Blacklist", callback_data=f"admin:user_unblacklist:{user_id}")
    else:
        kb.button(text="🚫 Add Blacklist", callback_data=f"admin:user_blacklist:{user_id}")
    kb.button(text="➕ Add Balance", callback_data=f"admin:user_wallet:add:{user_id}")
    kb.button(text="➖ Deduct Balance", callback_data=f"admin:user_wallet:deduct:{user_id}")
    kb.button(text="✏️ Set Exact Balance", callback_data=f"admin:user_wallet:set:{user_id}")
    kb.button(text="🧾 Transaction History", callback_data=f"admin:user_tx:{user_id}")
    kb.button(text="⬅️ User Management", callback_data="admin:users")
    kb.adjust(1)
    text = (
        "👤 <b>User Profile</b>\n"
        f"Name: {row['full_name'] or '—'}\n"
        f"Username: @{row['username'] or '—'}\n"
        f"Telegram ID: <code>{row['telegram_id']}</code>\n"
        f"Wallet: <b>₹{int(row['balance_paise'])/100:.2f}</b>\n"
        f"Blacklist: {'🚫 BLOCKED' if row['is_blacklisted'] else '✅ Active'}"
    )
    await cb.message.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data == "admin:users")
async def users_home(cb: CallbackQuery):
    if not is_main_admin(cb.from_user.id):
        await cb.answer("Main Admin only. Render mein MAIN_ADMIN_ID set karein.", show_alert=True)
        return
    await cb.answer()
    await cb.message.answer(
        "👥 <b>User & Wallet Control</b>\nMain Admin ke liye blacklist, wallet adjustments, exact balance, aur audit history.",
        reply_markup=user_admin_keyboard(),
    )


@router.callback_query(F.data == "admin:users_search")
async def user_search_start(cb: CallbackQuery, state: FSMContext):
    if not is_main_admin(cb.from_user.id):
        await cb.answer("Main Admin only.", show_alert=True)
        return
    await state.set_state(UserAdminFSM.search)
    await cb.answer()
    await cb.message.answer("Telegram ID, @username ya naam bhejein. Cancel: /cancel")


@router.message(UserAdminFSM.search, F.text)
async def user_search(msg: Message, state: FSMContext):
    if not is_main_admin(msg.from_user.id):
        await state.clear()
        return
    query = (msg.text or "").strip()
    if query == "/cancel":
        await state.clear()
        await msg.answer("Cancelled.")
        return
    uid = int(query) if query.isdigit() else -1
    pattern = "%" + query.lstrip("@") + "%"
    rows = await db().fetch(
        """SELECT u.telegram_id,u.username,COALESCE(u.full_name,u.first_name,'') AS full_name,
                  COALESCE(w.balance_paise,0) AS balance_paise,
                  EXISTS(SELECT 1 FROM user_blacklist b WHERE b.user_id=u.telegram_id) AS is_blacklisted
           FROM users u LEFT JOIN wallets w ON w.user_id=u.telegram_id
           WHERE u.telegram_id=$1 OR COALESCE(u.username,'') ILIKE $2 OR COALESCE(u.full_name,'') ILIKE $2 OR COALESCE(u.first_name,'') ILIKE $2
           ORDER BY u.telegram_id DESC LIMIT 15""",
        uid, pattern,
    )
    await state.clear()
    if not rows:
        await msg.answer("User nahi mila. User ko pehle /start karna hoga.")
        return
    kb = InlineKeyboardBuilder()
    text = "🔎 <b>Search Results</b>\n"
    for row in rows:
        text += f"\n• {row['full_name'] or 'Unknown'} | @{row['username'] or '—'} | ID <code>{row['telegram_id']}</code> | ₹{int(row['balance_paise'])/100:.2f} | {'🚫' if row['is_blacklisted'] else '✅'}"
        kb.button(text=f"👤 Open {str(row['telegram_id'])}", callback_data=f"admin:user_view:{row['telegram_id']}")
    kb.button(text="⬅️ User Management", callback_data="admin:users")
    kb.adjust(1)
    await msg.answer(text[:3500], reply_markup=kb.as_markup())


@router.callback_query(F.data == "admin:users_blacklisted")
async def users_blacklisted(cb: CallbackQuery):
    if not is_main_admin(cb.from_user.id):
        await cb.answer("Main Admin only.", show_alert=True)
        return
    rows = await db().fetch(
        """SELECT b.user_id,b.reason,b.created_at,u.username,COALESCE(u.full_name,u.first_name,'') AS full_name
           FROM user_blacklist b JOIN users u ON u.telegram_id=b.user_id
           ORDER BY b.created_at DESC LIMIT 30"""
    )
    kb = InlineKeyboardBuilder()
    text = "🚫 <b>Blacklisted Users</b>\n"
    for row in rows:
        text += f"\n• {row['full_name'] or 'Unknown'} | ID <code>{row['user_id']}</code> | {row['reason'][:100]}\n"
        kb.button(text=f"✅ Unblock {row['user_id']}", callback_data=f"admin:user_unblacklist:{row['user_id']}")
    if not rows:
        text += "\nKoi blacklisted user nahi hai."
    kb.button(text="⬅️ User Management", callback_data="admin:users")
    kb.adjust(1)
    await cb.answer()
    await cb.message.answer(text[:3500], reply_markup=kb.as_markup())


@router.callback_query(F.data == "admin:users_wallets")
async def users_wallets(cb: CallbackQuery):
    if not is_main_admin(cb.from_user.id):
        await cb.answer("Main Admin only.", show_alert=True)
        return
    rows = await db().fetch(
        """SELECT u.telegram_id,u.username,COALESCE(u.full_name,u.first_name,'') AS full_name,
                  COALESCE(w.balance_paise,0) AS balance_paise
           FROM users u LEFT JOIN wallets w ON w.user_id=u.telegram_id
           ORDER BY w.balance_paise DESC NULLS LAST,u.telegram_id DESC LIMIT 30"""
    )
    kb = InlineKeyboardBuilder()
    text = "💰 <b>Wallets (top 30)</b>\nSearch User se kisi bhi specific user ko dhoondh sakte hain.\n"
    for row in rows:
        text += f"\n{row['full_name'] or 'Unknown'} | ID <code>{row['telegram_id']}</code> | ₹{int(row['balance_paise'])/100:.2f}"
        kb.button(text=f"Manage {row['telegram_id']}", callback_data=f"admin:user_view:{row['telegram_id']}")
    kb.button(text="🔎 Search User", callback_data="admin:users_search")
    kb.button(text="⬅️ User Management", callback_data="admin:users")
    kb.adjust(1)
    await cb.answer()
    await cb.message.answer(text[:3500], reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("admin:user_view:"))
async def user_view(cb: CallbackQuery):
    if not is_main_admin(cb.from_user.id):
        await cb.answer("Main Admin only.", show_alert=True)
        return
    try:
        user_id = int(cb.data.rsplit(":", 1)[1])
    except ValueError:
        await cb.answer("Invalid user ID.", show_alert=True)
        return
    await cb.answer()
    await show_user(cb, user_id)


@router.callback_query(F.data.startswith("admin:user_blacklist:"))
async def user_blacklist_start(cb: CallbackQuery, state: FSMContext):
    if not is_main_admin(cb.from_user.id):
        await cb.answer("Main Admin only.", show_alert=True)
        return
    try:
        user_id = int(cb.data.rsplit(":", 1)[1])
    except ValueError:
        await cb.answer("Invalid user ID.", show_alert=True)
        return
    if user_id == MAIN_ADMIN_ID:
        await cb.answer("Main Admin ko blacklist nahi kar sakte.", show_alert=True)
        return
    await state.set_state(UserAdminFSM.blacklist_reason)
    await state.update_data(target_user_id=user_id)
    await cb.answer()
    await cb.message.answer(f"User <code>{user_id}</code> ko blacklist karne ka reason bhejein. Cancel: /cancel")


@router.message(UserAdminFSM.blacklist_reason, F.text)
async def user_blacklist_save(msg: Message, state: FSMContext):
    if not is_main_admin(msg.from_user.id):
        await state.clear()
        return
    reason = (msg.text or "").strip()
    if reason == "/cancel":
        await state.clear()
        await msg.answer("Cancelled.")
        return
    if not reason or len(reason) > 300:
        await msg.answer("Reason 1–300 characters ka bhejein. Cancel: /cancel")
        return
    data = await state.get_data()
    user_id = int(data["target_user_id"])
    await db().execute(
        """INSERT INTO user_blacklist(user_id,reason,blacklisted_by,created_at,updated_at)
           VALUES($1,$2,$3,NOW(),NOW())
           ON CONFLICT(user_id) DO UPDATE SET reason=EXCLUDED.reason,blacklisted_by=EXCLUDED.blacklisted_by,created_at=NOW(),updated_at=NOW()""",
        user_id, reason, msg.from_user.id,
    )
    await db().execute(
        "INSERT INTO admin_audit_log(admin_id,action,target_user_id,details) VALUES($1,'blacklist',$2,$3::jsonb)",
        msg.from_user.id, user_id, json.dumps({"reason": reason}),
    )
    await state.clear()
    await msg.answer(f"🚫 User <code>{user_id}</code> blacklist ho gaya. Wallet balance, purchases aur transaction history safe hain.", reply_markup=user_admin_keyboard())


@router.callback_query(F.data.startswith("admin:user_unblacklist:"))
async def user_unblacklist(cb: CallbackQuery):
    if not is_main_admin(cb.from_user.id):
        await cb.answer("Main Admin only.", show_alert=True)
        return
    try:
        user_id = int(cb.data.rsplit(":", 1)[1])
    except ValueError:
        await cb.answer("Invalid user ID.", show_alert=True)
        return
    async with db().acquire() as conn:
        async with conn.transaction():
            deleted = await conn.fetchval("DELETE FROM user_blacklist WHERE user_id=$1 RETURNING user_id", user_id)
            await conn.execute(
                "INSERT INTO admin_audit_log(admin_id,action,target_user_id,details) VALUES($1,'unblacklist',$2,'{}'::jsonb)",
                cb.from_user.id, user_id,
            )
    await cb.answer("Blacklist removed." if deleted else "User pehle se active hai.", show_alert=True)
    if cb.message:
        await cb.message.answer(f"✅ User <code>{user_id}</code> ab blacklist mein nahi hai.", reply_markup=user_admin_keyboard())


@router.callback_query(F.data.startswith("admin:user_wallet:"))
async def user_wallet_action_start(cb: CallbackQuery, state: FSMContext):
    if not is_main_admin(cb.from_user.id):
        await cb.answer("Main Admin only.", show_alert=True)
        return
    parts = cb.data.split(":")
    # Expected callback_data: admin:user_wallet:<action>:<user_id>
    if len(parts) != 4:
        await cb.answer("Invalid wallet action.", show_alert=True)
        return
    action = parts[2]
    try:
        user_id = int(parts[3])
    except ValueError:
        await cb.answer("Invalid user ID.", show_alert=True)
        return
    if action not in {"add", "deduct", "set"}:
        await cb.answer("Invalid wallet action.", show_alert=True)
        return
    await state.set_state(UserAdminFSM.wallet_amount)
    await state.update_data(wallet_action=action, target_user_id=user_id)
    await cb.answer()
    label = {"add": "add karna", "deduct": "deduct karna", "set": "exact balance set karna"}[action]
    await cb.message.answer(f"User <code>{user_id}</code> ke wallet mein {label} hai. Amount INR mein bhejein (example: 100 ya 25.50). Cancel: /cancel")


@router.message(UserAdminFSM.wallet_amount, F.text)
async def user_wallet_amount_save(msg: Message, state: FSMContext):
    if not is_main_admin(msg.from_user.id):
        await state.clear()
        return
    raw = (msg.text or "").strip()
    if raw == "/cancel":
        await state.clear()
        await msg.answer("Cancelled.")
        return
    try:
        amount_paise = int(round(float(raw.replace("₹", "").replace(",", "")) * 100))
    except ValueError:
        await msg.answer("Valid amount INR mein bhejein. Example: 100 ya 25.50. Cancel: /cancel")
        return
    if amount_paise < 0 or amount_paise > 100000000000:
        await msg.answer("Amount 0 ya usse zyada aur limit ke andar hona chahiye.")
        return
    data = await state.get_data()
    user_id = int(data["target_user_id"])
    action = data["wallet_action"]
    try:
        async with db().acquire() as conn:
            async with conn.transaction():
                user = await conn.fetchrow("SELECT telegram_id FROM users WHERE telegram_id=$1 FOR UPDATE", user_id)
                if not user:
                    await msg.answer("User nahi mila. Pehle user ko bot /start karna hoga.")
                    await state.clear()
                    return
                await conn.execute("INSERT INTO wallets(user_id,balance_paise) VALUES($1,0) ON CONFLICT(user_id) DO NOTHING", user_id)
                wallet = await conn.fetchrow("SELECT balance_paise FROM wallets WHERE user_id=$1 FOR UPDATE", user_id)
                old_balance = int(wallet["balance_paise"])
                if action == "add":
                    new_balance = old_balance + amount_paise
                    delta = amount_paise
                elif action == "deduct":
                    if amount_paise > old_balance:
                        await msg.answer(f"❌ Wallet balance sirf ₹{old_balance/100:.2f} hai. Negative balance allow nahi hai.")
                        return
                    new_balance = old_balance - amount_paise
                    delta = -amount_paise
                else:
                    new_balance = amount_paise
                    delta = new_balance - old_balance
                if delta == 0:
                    await msg.answer("Balance mein koi change nahi hua; transaction create nahi ki.")
                    await state.clear()
                    return
                await conn.execute("UPDATE wallets SET balance_paise=$1,updated_at=NOW() WHERE user_id=$2", new_balance, user_id)
                ref = "admin-adjust-" + uuid.uuid4().hex
                await conn.execute(
                    """INSERT INTO wallet_transactions(user_id,kind,amount_paise,balance_after_paise,reference,details)
                       VALUES($1,'admin_adjustment',$2,$3,$4,$5::jsonb)""",
                    user_id, delta, new_balance, ref,
                    json.dumps({"action": action, "admin_id": msg.from_user.id, "reason": "Main Admin manual wallet adjustment", "previous_balance_paise": old_balance}),
                )
                await conn.execute(
                    "INSERT INTO admin_audit_log(admin_id,action,target_user_id,details) VALUES($1,$2,$3,$4::jsonb)",
                    msg.from_user.id, "wallet_" + action, user_id,
                    json.dumps({"old_balance_paise": old_balance, "new_balance_paise": new_balance, "delta_paise": delta, "reference": ref}),
                )
    except Exception:
        log.exception("Main admin wallet adjustment failed admin=%s user=%s action=%s", msg.from_user.id, user_id, action)
        await msg.answer("⚠️ Wallet update nahi hua. Database logs check karein; transaction rollback ho gaya hoga.")
        return
    await state.clear()
    await msg.answer(
        f"✅ Wallet updated\nUser: <code>{user_id}</code>\nOld balance: ₹{old_balance/100:.2f}\nNew balance: ₹{new_balance/100:.2f}\nChange: {'+' if delta > 0 else ''}₹{delta/100:.2f}\nReference: <code>{ref}</code>",
        reply_markup=user_admin_keyboard(),
    )


@router.callback_query(F.data.startswith("admin:user_tx:"))
async def user_transactions(cb: CallbackQuery):
    if not is_main_admin(cb.from_user.id):
        await cb.answer("Main Admin only.", show_alert=True)
        return
    try:
        user_id = int(cb.data.rsplit(":", 1)[1])
    except ValueError:
        await cb.answer("Invalid user ID.", show_alert=True)
        return
    rows = await db().fetch(
        """SELECT id,kind,amount_paise,balance_after_paise,reference,details::text AS details_text,created_at
           FROM wallet_transactions WHERE user_id=$1 ORDER BY id DESC LIMIT 20""",
        user_id,
    )
    text = f"🧾 <b>Wallet History</b> — <code>{user_id}</code>\n"
    for row in rows:
        amount = int(row["amount_paise"])
        text += f"\n#{row['id']} {row['kind']} {'+' if amount > 0 else ''}₹{amount/100:.2f}\nBalance: ₹{int(row['balance_after_paise'])/100:.2f}\nRef: <code>{row['reference'][:40]}</code>\n{str(row['details_text'] or '{}')[:180]}\n{row['created_at']}\n"
    if not rows:
        text += "\nNo wallet transactions found."
    kb = InlineKeyboardBuilder()
    kb.button(text="👤 User Profile", callback_data=f"admin:user_view:{user_id}")
    kb.button(text="⬅️ User Management", callback_data="admin:users")
    kb.adjust(1)
    await cb.answer()
    await cb.message.answer(text[:3900], reply_markup=kb.as_markup())


@router.callback_query(F.data == "admin:users_transactions")
async def all_wallet_transactions(cb: CallbackQuery):
    if not is_main_admin(cb.from_user.id):
        await cb.answer("Main Admin only.", show_alert=True)
        return
    rows = await db().fetch(
        """SELECT t.id,t.user_id,t.kind,t.amount_paise,t.balance_after_paise,t.reference,t.created_at,
                  COALESCE(u.username,'') AS username,COALESCE(u.full_name,u.first_name,'') AS full_name
           FROM wallet_transactions t JOIN users u ON u.telegram_id=t.user_id
           ORDER BY t.id DESC LIMIT 25"""
    )
    text = "🧾 <b>Latest Wallet Transactions</b>\n"
    for row in rows:
        amount = int(row["amount_paise"])
        text += f"\n#{row['id']} | {row['full_name'] or 'Unknown'} (@{row['username'] or '—'})\nID <code>{row['user_id']}</code> | {row['kind']} {'+' if amount > 0 else ''}₹{amount/100:.2f} | balance ₹{int(row['balance_after_paise'])/100:.2f}\n"
    if not rows:
        text += "\nNo transactions yet."
    await cb.answer()
    await cb.message.answer(text[:3900], reply_markup=user_admin_keyboard())
