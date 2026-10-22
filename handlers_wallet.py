import logging
import uuid
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from db import db
from utils import is_admin, notify_admins

router = Router()
log = logging.getLogger(__name__)
MIN_DEPOSIT = 2500  # paise = ₹25


class WalletFSM(StatesGroup):
    deposit_amount = State()
    deposit_proof = State()
    deposit_utr = State()
    purchase_quantity = State()
    inventory_add = State()
    category_price = State()
    qr_upload = State()
    history_search = State()


def money(paise):
    return "₹" + format(int(paise) / 100, ".2f").rstrip("0").rstrip(".")


def admin_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Deposits", callback_data="admin:wallet_deposits")
    kb.button(text="📁 JSON Inventory", callback_data="admin:wallet_inventory")
    kb.button(text="💵 Category Prices", callback_data="admin:wallet_prices")
    kb.button(text="🧾 User / Transaction History", callback_data="admin:wallet_history")
    kb.button(text="📷 Set PhonePe QR", callback_data="admin:wallet_qr")
    kb.button(text="⬅️ Admin Home", callback_data="admin:home")
    kb.adjust(1)
    return kb.as_markup()


async def user_wallet_id(user):
    await db().execute(
        """INSERT INTO users(telegram_id,username,first_name,full_name)
           VALUES($1,$2,$3,$4) ON CONFLICT(telegram_id) DO UPDATE SET
           username=EXCLUDED.username, first_name=EXCLUDED.first_name, full_name=EXCLUDED.full_name""",
        user.id, user.username, user.first_name, user.full_name,
    )
    await db().execute("INSERT INTO wallets(user_id) VALUES($1) ON CONFLICT(user_id) DO NOTHING", user.id)


@router.callback_query(F.data == "menu:balance")
async def wallet_menu(cb: CallbackQuery):
    await user_wallet_id(cb.from_user)
    bal = await db().fetchval("SELECT balance_paise FROM wallets WHERE user_id=$1", cb.from_user.id) or 0
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Add Balance", callback_data="wallet:deposit")
    kb.button(text="🧾 My Transactions", callback_data="wallet:history")
    kb.button(text="⬅️ Main Menu", callback_data="user:home")
    kb.adjust(1)
    await cb.answer()
    await cb.message.answer("💰 <b>My Wallet</b>\nAvailable balance: <b>" + money(bal) + "</b>\nMinimum deposit: ₹25", reply_markup=kb.as_markup())


@router.callback_query(F.data == "wallet:deposit")
async def deposit_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(WalletFSM.deposit_amount)
    await cb.answer()
    await cb.message.answer("Deposit amount bhejein. Minimum ₹25.\nCancel: /cancel")


@router.message(WalletFSM.deposit_amount, F.text)
async def deposit_amount(msg: Message, state: FSMContext):
    raw = (msg.text or "").strip()
    if raw == "/cancel":
        await state.clear()
        await msg.answer("Deposit cancel ho gaya.")
        return
    try:
        amount = int(round(float(raw.replace("₹", "").replace(",", "")) * 100))
    except ValueError:
        await msg.answer("Amount number mein bhejein. Example: 100")
        return
    if amount < MIN_DEPOSIT or amount > 100000000:
        await msg.answer("Minimum deposit ₹25 hai. Valid amount bhejein.")
        return
    qr = await db().fetchval("SELECT value FROM bot_settings WHERE key='phonepe_qr_file_id'")
    if not qr:
        await state.clear()
        await msg.answer("PhonePe QR abhi set nahi hai. Admin se contact karein.")
        return
    await state.update_data(deposit_amount_paise=amount)
    await state.set_state(WalletFSM.deposit_proof)
    try:
        await msg.answer_photo(qr, caption="📱 PhonePe QR\nAmount: <b>" + money(amount) + "</b>\nPayment karne ke baad screenshot bhejein. Sirf admin approval ke baad balance add hoga.")
    except Exception:
        log.exception("Could not send configured PhonePe QR")
        await msg.answer("QR send nahi ho paya. Admin ko QR dobara set karna hoga.")
        await state.clear()
        return
    await msg.answer("Payment ka screenshot/photo bhejein. Cancel: /cancel")


@router.message(WalletFSM.deposit_proof)
async def deposit_proof(msg: Message, state: FSMContext, bot: Bot):
    if msg.text and msg.text.strip() == "/cancel":
        await state.clear()
        await msg.answer("Deposit cancel ho gaya.")
        return
    if msg.photo:
        file_id, proof_type = msg.photo[-1].file_id, "photo"
    elif msg.document and (msg.document.mime_type or "").startswith("image/"):
        file_id, proof_type = msg.document.file_id, "document"
    else:
        await msg.answer("Payment screenshot image ke roop mein bhejein. Cancel: /cancel")
        return
    data = await state.get_data()
    await state.update_data(proof_file_id=file_id, proof_type=proof_type)
    await state.set_state(WalletFSM.deposit_utr)
    await msg.answer("Ab payment ka UTR / transaction ID bhejein. Agar UTR nahi mila, to NO likhein. Cancel: /cancel")


@router.message(WalletFSM.deposit_utr, F.text)
async def deposit_submit(msg: Message, state: FSMContext, bot: Bot):
    raw = (msg.text or "").strip()
    if raw == "/cancel":
        await state.clear()
        await msg.answer("Deposit cancel ho gaya.")
        return
    utr = None if raw.upper() == "NO" else raw[:100]
    data = await state.get_data()
    await user_wallet_id(msg.from_user)
    try:
        async with db().acquire() as conn:
            async with conn.transaction():
                dep = await conn.fetchrow(
                    """INSERT INTO wallet_deposits(user_id,amount_paise,utr,proof_file_id,proof_type)
                       VALUES($1,$2,$3,$4,$5) RETURNING id""",
                    msg.from_user.id, data["deposit_amount_paise"], utr, data["proof_file_id"], data["proof_type"]
                )
    except Exception:
        log.exception("Deposit submission failed for user %s", msg.from_user.id)
        await msg.answer("Request save nahi hui. UTR pehle submit hua ho sakta hai; admin se contact karein.")
        return
    await state.clear()
    await msg.answer("✅ Deposit request #" + str(dep["id"]) + " admin ko bhej di. Approval ke baad balance update hoga.")
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Approve", callback_data="admin:deposit_approve:" + str(dep["id"]))
    kb.button(text="❌ Reject", callback_data="admin:deposit_reject:" + str(dep["id"]))
    kb.adjust(2)
    user = await db().fetchrow("SELECT full_name,username FROM users WHERE telegram_id=$1", msg.from_user.id)
    for aid in await _admin_ids():
        try:
            await bot.send_photo(
                aid, data["proof_file_id"],
                caption="💰 <b>Deposit request #" + str(dep["id"]) + "</b>\nUser: " + (user["full_name"] or "Unknown") +
                "\nUsername: @" + (user["username"] or "—") + "\nID: <code>" + str(msg.from_user.id) +
                "</code>\nAmount: <b>" + money(data["deposit_amount_paise"]) + "</b>\nUTR: " + (utr or "Not provided"),
                reply_markup=kb.as_markup()
            )
        except Exception:
            log.exception("Could not notify admin %s for deposit %s", aid, dep["id"])


async def _admin_ids():
    from utils import get_all_admin_ids
    return await get_all_admin_ids()


@router.callback_query(F.data.startswith(("admin:deposit_approve:", "admin:deposit_reject:")))
async def deposit_review(cb: CallbackQuery, bot: Bot):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True)
        return
    action, raw_id = cb.data.rsplit(":", 1)
    dep_id = int(raw_id)
    user_id = None
    amount = None
    async with db().acquire() as conn:
        async with conn.transaction():
            dep = await conn.fetchrow("SELECT * FROM wallet_deposits WHERE id=$1 FOR UPDATE", dep_id)
            if not dep or dep["status"] != "pending":
                await cb.answer("Request pehle hi process ho chuki hai.", show_alert=True)
                return
            user_id, amount = dep["user_id"], dep["amount_paise"]
            if action == "admin:deposit_approve":
                await conn.execute("INSERT INTO wallets(user_id) VALUES($1) ON CONFLICT(user_id) DO NOTHING", user_id)
                wallet = await conn.fetchrow("SELECT balance_paise FROM wallets WHERE user_id=$1 FOR UPDATE", user_id)
                new_balance = wallet["balance_paise"] + amount
                await conn.execute("UPDATE wallets SET balance_paise=$1,updated_at=NOW() WHERE user_id=$2", new_balance, user_id)
                await conn.execute("UPDATE wallet_deposits SET status='approved',reviewed_by=$1,reviewed_at=NOW() WHERE id=$2", cb.from_user.id, dep_id)
                await conn.execute(
                    """INSERT INTO wallet_transactions(user_id,kind,amount_paise,balance_after_paise,reference,details)
                       VALUES($1,'deposit',$2,$3,$4,jsonb_build_object('deposit_id',$5,'reviewed_by',$6,'utr',$7))""",
                    user_id, amount, new_balance, "deposit:" + str(dep_id), dep_id, cb.from_user.id, dep["utr"]
                )
            else:
                await conn.execute("UPDATE wallet_deposits SET status='rejected',reviewed_by=$1,reviewed_at=NOW() WHERE id=$2", cb.from_user.id, dep_id)
    if action == "admin:deposit_approve":
        await cb.answer("Deposit approved.")
        try:
            await bot.send_message(user_id, "✅ Deposit #" + str(dep_id) + " approved. Wallet mein " + money(amount) + " add ho gaye.")
        except Exception:
            log.exception("Could not notify user about approved deposit %s", dep_id)
        await cb.message.answer("Approved: #" + str(dep_id) + " — " + money(amount))
    else:
        await cb.answer("Deposit rejected.")
        try:
            await bot.send_message(user_id, "❌ Deposit request #" + str(dep_id) + " reject hui. Details ke liye admin se contact karein.")
        except Exception:
            log.exception("Could not notify user about rejected deposit %s", dep_id)
        await cb.message.answer("Rejected: #" + str(dep_id))


@router.callback_query(F.data == "menu:buyfiles")
async def buy_categories(cb: CallbackQuery):
    rows = await db().fetch("SELECT id,label,price_paise FROM inventory_categories WHERE is_active=TRUE ORDER BY position,id")
    kb = InlineKeyboardBuilder()
    for row in rows:
        count = await db().fetchval("SELECT COUNT(*) FROM digital_inventory WHERE category_id=$1 AND status='available'", row["id"])
        kb.button(text=row["label"] + " — " + money(row["price_paise"]) + " (" + str(count) + " available)", callback_data="files:category:" + str(row["id"]))
    kb.button(text="⬅️ Main Menu", callback_data="user:home")
    kb.adjust(1)
    await cb.answer()
    await cb.message.answer("🛒 <b>Available JSON files</b>\nCategory choose karein:", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("files:category:"))
async def choose_inventory_category(cb: CallbackQuery, state: FSMContext):
    cat_id = int(cb.data.rsplit(":", 1)[1])
    cat = await db().fetchrow("SELECT * FROM inventory_categories WHERE id=$1 AND is_active=TRUE", cat_id)
    count = await db().fetchval("SELECT COUNT(*) FROM digital_inventory WHERE category_id=$1 AND status='available'", cat_id)
    await cb.answer()
    if not cat or not count:
        await cb.message.answer("Is category mein abhi stock available nahi hai.")
        return
    await state.set_state(WalletFSM.purchase_quantity)
    await state.update_data(category_id=cat_id)
    await cb.message.answer(cat["label"] + "\nPrice per file: " + money(cat["price_paise"]) + "\nAvailable: " + str(count) + "\nKitni files chahiye? Quantity number bhejein. Cancel: /cancel")


@router.message(WalletFSM.purchase_quantity, F.text)
async def purchase_quantity(msg: Message, state: FSMContext, bot: Bot):
    raw = (msg.text or "").strip()
    if raw == "/cancel":
        await state.clear()
        await msg.answer("Purchase cancel ho gayi.")
        return
    if not raw.isdigit() or not 1 <= int(raw) <= 100:
        await msg.answer("Quantity 1 se 100 ke beech number mein bhejein.")
        return
    qty = int(raw)
    data = await state.get_data()
    cat_id = int(data["category_id"])
    await user_wallet_id(msg.from_user)
    purchase_id = uuid.uuid4()
    chosen = []
    try:
        async with db().acquire() as conn:
            async with conn.transaction():
                cat = await conn.fetchrow("SELECT * FROM inventory_categories WHERE id=$1 AND is_active=TRUE FOR UPDATE", cat_id)
                if not cat:
                    await msg.answer("Category available nahi hai.")
                    return
                rows = await conn.fetch(
                    """SELECT id FROM digital_inventory WHERE category_id=$1 AND status='available'
                       ORDER BY id FOR UPDATE SKIP LOCKED LIMIT $2""", cat_id, qty
                )
                if len(rows) < qty:
                    await msg.answer("Itna stock available nahi hai. Available: " + str(len(rows)) + ".")
                    return
                total = cat["price_paise"] * qty
                wallet = await conn.fetchrow("SELECT balance_paise FROM wallets WHERE user_id=$1 FOR UPDATE", msg.from_user.id)
                if not wallet or wallet["balance_paise"] < total:
                    await msg.answer("Wallet balance kam hai. Total " + money(total) + " chahiye. Pehle Add Balance karein.")
                    return
                new_balance = wallet["balance_paise"] - total
                await conn.execute("UPDATE wallets SET balance_paise=$1,updated_at=NOW() WHERE user_id=$2", new_balance, msg.from_user.id)
                await conn.execute(
                    """INSERT INTO inventory_purchases(purchase_id,user_id,category_id,quantity,unit_price_paise,total_paise,status)
                       VALUES($1,$2,$3,$4,$5,$6,'paid')""",
                    purchase_id, msg.from_user.id, cat_id, qty, cat["price_paise"], total
                )
                await conn.execute(
                    """INSERT INTO wallet_transactions(user_id,kind,amount_paise,balance_after_paise,reference,details)
                       VALUES($1,'purchase',$2,$3,$4,jsonb_build_object('purchase_id',$5,'category_id',$6,'quantity',$7))""",
                    msg.from_user.id, -total, new_balance, "purchase:" + str(purchase_id), str(purchase_id), cat_id, qty
                )
                for row in rows:
                    item = await conn.fetchrow(
                        """UPDATE digital_inventory SET status='sold',sold_to=$1,sold_at=NOW(),purchase_id=$2
                           WHERE id=$3 AND status='available' RETURNING *""",
                        msg.from_user.id, purchase_id, row["id"]
                    )
                    if item:
                        chosen.append(dict(item))
                        await conn.execute("INSERT INTO inventory_purchase_items(purchase_id,inventory_id) VALUES($1,$2)", purchase_id, item["id"])
                if len(chosen) != qty:
                    raise RuntimeError("Inventory count changed during purchase")
                await conn.execute("UPDATE inventory_purchases SET status='delivery_pending' WHERE purchase_id=$1", purchase_id)
    except Exception:
        log.exception("Inventory purchase failed for user %s", msg.from_user.id)
        await msg.answer("Purchase complete nahi hui. Balance aur stock verify karke dobara try karein.")
        return
    await state.clear()
    await msg.answer("✅ Purchase successful\nQuantity: " + str(qty) + "\nTotal: " + money(total) + "\nRemaining balance: " + money(new_balance) + "\nOrder ID: <code>" + str(purchase_id) + "</code>\nFiles ab sirf aapke order mein assigned hain.")
    delivery_ok = True
    for item in chosen:
        try:
            if item["item_type"] == "text":
                await bot.send_message(msg.from_user.id, item["text_content"] or "")
            elif item["item_type"] == "photo":
                await bot.send_photo(msg.from_user.id, item["telegram_file_id"], caption=item["caption"] or None)
            else:
                await bot.send_document(msg.from_user.id, item["telegram_file_id"], caption=item["caption"] or None)
            await db().execute("UPDATE inventory_purchase_items SET delivered_at=NOW() WHERE purchase_id=$1 AND inventory_id=$2", purchase_id, item["id"])
        except Exception:
            delivery_ok = False
            log.exception("Inventory delivery failed item %s purchase %s", item["id"], purchase_id)
    await db().execute("UPDATE inventory_purchases SET status=$1 WHERE purchase_id=$2", "delivered" if delivery_ok else "delivery_pending", purchase_id)
    await notify_admins(bot, "🛒 JSON purchase\nUser: " + msg.from_user.full_name + "\nID: " + str(msg.from_user.id) + "\nCategory ID: " + str(cat_id) + "\nQuantity: " + str(qty) + "\nTotal: " + money(total) + "\nOrder: " + str(purchase_id))


@router.callback_query(F.data == "menu:purchases")
async def user_purchases(cb: CallbackQuery):
    rows = await db().fetch(
        """SELECT p.purchase_id,p.quantity,p.total_paise,p.status,p.created_at,c.label
           FROM inventory_purchases p JOIN inventory_categories c ON c.id=p.category_id
           WHERE p.user_id=$1 ORDER BY p.created_at DESC LIMIT 10""", cb.from_user.id
    )
    await cb.answer()
    if not rows:
        await cb.message.answer("Abhi koi purchase history nahi hai.")
        return
    text = "📦 <b>My Purchases</b>\n"
    for r in rows:
        text += "\n• " + r["label"] + " × " + str(r["quantity"]) + " — " + money(r["total_paise"]) + "\n  " + str(r["status"]) + " | " + str(r["created_at"]) + "\n  <code>" + str(r["purchase_id"]) + "</code>\n"
    await cb.message.answer(text)


@router.callback_query(F.data == "wallet:history")
async def wallet_history(cb: CallbackQuery):
    rows = await db().fetch("SELECT kind,amount_paise,balance_after_paise,reference,created_at FROM wallet_transactions WHERE user_id=$1 ORDER BY id DESC LIMIT 15", cb.from_user.id)
    await cb.answer()
    if not rows:
        await cb.message.answer("Abhi koi wallet transaction nahi hai.")
        return
    text = "🧾 <b>Wallet History</b>\n"
    for r in rows:
        sign = "+" if r["amount_paise"] > 0 else ""
        text += "\n• " + r["kind"] + ": " + sign + money(r["amount_paise"]) + "\n  Balance: " + money(r["balance_after_paise"]) + "\n  Ref: <code>" + r["reference"][:40] + "</code>\n  " + str(r["created_at"]) + "\n"
    await cb.message.answer(text)


@router.callback_query(F.data == "admin:wallet_deposits")
async def admin_deposits(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True); return
    rows = await db().fetch("""SELECT d.id,d.user_id,d.amount_paise,d.utr,d.status,d.created_at,u.full_name,u.username
        FROM wallet_deposits d JOIN users u ON u.telegram_id=d.user_id ORDER BY d.created_at DESC LIMIT 20""")
    kb = InlineKeyboardBuilder()
    text = "💰 <b>Deposit Requests</b>\n"
    for r in rows:
        text += "\n#" + str(r["id"]) + " — " + money(r["amount_paise"]) + " — " + r["status"] + "\n" + (r["full_name"] or "Unknown") + " | ID " + str(r["user_id"]) + "\nUTR: " + (r["utr"] or "—") + "\n"
        if r["status"] == "pending":
            kb.button(text="Review #" + str(r["id"]), callback_data="admin:deposit_detail:" + str(r["id"]))
    kb.button(text="⬅️ Wallet Admin", callback_data="admin:wallet_home")
    kb.adjust(1)
    await cb.answer()
    await cb.message.answer(text if rows else "Abhi deposit request nahi hai.", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("admin:deposit_detail:"))
async def admin_deposit_detail(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True); return
    dep_id = int(cb.data.rsplit(":", 1)[1])
    r = await db().fetchrow("""SELECT d.*,u.full_name,u.username FROM wallet_deposits d JOIN users u ON u.telegram_id=d.user_id WHERE d.id=$1""", dep_id)
    if not r:
        await cb.answer("Request nahi mili.", show_alert=True); return
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Approve", callback_data="admin:deposit_approve:" + str(dep_id))
    kb.button(text="❌ Reject", callback_data="admin:deposit_reject:" + str(dep_id))
    kb.button(text="⬅️ Deposits", callback_data="admin:wallet_deposits")
    kb.adjust(2,1)
    await cb.answer()
    caption = "Deposit #" + str(dep_id) + "\nUser: " + (r["full_name"] or "Unknown") + "\nUsername: @" + (r["username"] or "—") + "\nID: " + str(r["user_id"]) + "\nAmount: " + money(r["amount_paise"]) + "\nUTR: " + (r["utr"] or "—") + "\nStatus: " + r["status"]
    if r["proof_type"] == "photo":
        await cb.message.answer_photo(r["proof_file_id"], caption=caption, reply_markup=kb.as_markup())
    else:
        await cb.message.answer_document(r["proof_file_id"], caption=caption, reply_markup=kb.as_markup())


@router.callback_query(F.data == "admin:wallet_home")
async def admin_wallet_home(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True); return
    await cb.answer()
    await cb.message.answer("💼 <b>Wallet & JSON Admin</b>", reply_markup=admin_kb())


@router.callback_query(F.data == "admin:wallet_inventory")
async def admin_inventory(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True); return
    cats = await db().fetch("SELECT id,label,price_paise,is_active FROM inventory_categories ORDER BY position,id")
    kb = InlineKeyboardBuilder()
    text = "📁 <b>JSON Inventory</b>\n"
    for c in cats:
        count = await db().fetchval("SELECT COUNT(*) FROM digital_inventory WHERE category_id=$1 AND status='available'", c["id"])
        text += "\n" + c["label"] + " — " + str(count) + " available — " + ("Active" if c["is_active"] else "Disabled")
        kb.button(text="➕ Add to " + c["label"][:22], callback_data="admin:inventory_add:" + str(c["id"]))
        kb.button(text="📋 View stock " + c["label"][:18], callback_data="admin:inventory_view:" + str(c["id"]))
    kb.button(text="⬅️ Wallet Admin", callback_data="admin:wallet_home")
    kb.adjust(1)
    await cb.answer()
    await cb.message.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("admin:inventory_view:"))
async def admin_inventory_view(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True); return
    cat_id = int(cb.data.rsplit(":", 1)[1])
    rows = await db().fetch("SELECT id,item_type,file_name,status,created_at FROM digital_inventory WHERE category_id=$1 ORDER BY id DESC LIMIT 30", cat_id)
    kb = InlineKeyboardBuilder()
    text = "📋 <b>Inventory items</b> (latest 30)\n"
    for r in rows:
        text += "\n#" + str(r["id"]) + " — " + (r["file_name"] or r["item_type"]) + " — " + r["status"]
        if r["status"] == "available":
            kb.button(text="🗑 Delete #" + str(r["id"]), callback_data="admin:inventory_delete:" + str(r["id"]))
    kb.button(text="⬅️ Inventory", callback_data="admin:wallet_inventory")
    kb.adjust(1)
    await cb.answer()
    await cb.message.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("admin:inventory_delete:"))
async def admin_inventory_delete(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True); return
    item_id = int(cb.data.rsplit(":", 1)[1])
    updated = await db().fetchval("UPDATE digital_inventory SET status='disabled' WHERE id=$1 AND status='available' RETURNING id", item_id)
    await cb.answer("Stock se remove kar diya." if updated else "Item available nahi hai.", show_alert=True)


@router.callback_query(F.data.startswith("admin:inventory_add:"))
async def inventory_add_start(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True); return
    cat_id = int(cb.data.rsplit(":", 1)[1])
    cat = await db().fetchrow("SELECT id,label FROM inventory_categories WHERE id=$1", cat_id)
    if not cat:
        await cb.answer("Category nahi mili.", show_alert=True); return
    await state.set_state(WalletFSM.inventory_add)
    await state.update_data(inventory_category_id=cat_id)
    await cb.answer()
    await cb.message.answer("📁 " + cat["label"] + "\nHar JSON document ya text item alag message mein bhejein. Multiple files bhej sakte hain; har file alag inventory item banegi. Sirf authorized dummy/test JSON files add karein.\nDone: /done | Cancel: /cancel")


@router.message(WalletFSM.inventory_add)
async def inventory_add_save(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        await state.clear(); return
    raw = (msg.text or "").strip()
    if raw == "/cancel":
        await state.clear(); await msg.answer("Inventory upload cancel.")
        return
    if raw == "/done":
        data = await state.get_data()
        count = int(data.get("inventory_added", 0))
        await state.clear()
        await msg.answer("✅ " + str(count) + " item(s) inventory mein save ho gaye.")
        return
    data = await state.get_data()
    cat_id = int(data["inventory_category_id"])
    if msg.document:
        name = msg.document.file_name or "file.json"
        if not name.lower().endswith(".json"):
            await msg.answer("Sirf .json documents accept hote hain. File ko .json extension ke saath upload karein.")
            return
        item_type, file_id, text_content = "document", msg.document.file_id, None
        mime, size, caption = msg.document.mime_type, msg.document.file_size, msg.caption
    elif msg.text and raw:
        item_type, file_id, text_content = "text", None, raw[:4000]
        name, mime, size, caption = None, "application/json", None, None
    else:
        await msg.answer("JSON document ya dummy/test JSON text bhejein. /done jab finish ho.")
        return
    try:
        await db().execute(
            """INSERT INTO digital_inventory(category_id,item_type,telegram_file_id,file_name,mime_type,file_size,caption,text_content,added_by)
               VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
            cat_id, item_type, file_id, name, mime, size, caption, text_content, msg.from_user.id
        )
    except Exception:
        log.exception("Could not save inventory item")
        await msg.answer("Yeh item save nahi hua. Dobara try karein.")
        return
    count = int(data.get("inventory_added", 0)) + 1
    await state.update_data(inventory_added=count)
    await msg.answer("✅ Item #" + str(count) + " save ho gaya. Agli file/text bhejein ya /done.")


@router.callback_query(F.data == "admin:wallet_prices")
async def admin_prices(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True); return
    rows = await db().fetch("SELECT id,label,price_paise,is_active FROM inventory_categories ORDER BY position,id")
    kb = InlineKeyboardBuilder()
    text = "💵 <b>Category Prices</b>\n"
    for r in rows:
        text += "\n" + r["label"] + " — " + money(r["price_paise"]) + " — " + ("Active" if r["is_active"] else "Disabled")
        kb.button(text="✏️ Edit " + r["label"][:24], callback_data="admin:wallet_price_edit:" + str(r["id"]))
        kb.button(text=("⏸ Disable " if r["is_active"] else "▶️ Enable ") + r["label"][:18], callback_data="admin:wallet_cat_toggle:" + str(r["id"]))
    kb.button(text="⬅️ Wallet Admin", callback_data="admin:wallet_home")
    kb.adjust(1)
    await cb.answer()
    await cb.message.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("admin:wallet_price_edit:"))
async def price_edit_start(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True); return
    cat_id = int(cb.data.rsplit(":", 1)[1])
    await state.set_state(WalletFSM.category_price)
    await state.update_data(price_category_id=cat_id)
    await cb.answer()
    await cb.message.answer("Naya price ₹ mein bhejein. Example: 25. Cancel: /cancel")


@router.message(WalletFSM.category_price, F.text)
async def price_edit_save(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        await state.clear(); return
    raw = (msg.text or "").strip()
    if raw == "/cancel":
        await state.clear(); await msg.answer("Cancelled."); return
    try:
        price = int(round(float(raw.replace("₹", "").replace(",", "")) * 100))
    except ValueError:
        await msg.answer("Valid price bhejein, example 25."); return
    if price < 0 or price > 100000000:
        await msg.answer("Price range valid nahi hai."); return
    data = await state.get_data()
    await db().execute("UPDATE inventory_categories SET price_paise=$1,updated_at=NOW() WHERE id=$2", price, data["price_category_id"])
    await state.clear()
    await msg.answer("✅ Category price update ho gaya: " + money(price))


@router.callback_query(F.data.startswith("admin:wallet_cat_toggle:"))
async def category_toggle(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True); return
    cat_id = int(cb.data.rsplit(":", 1)[1])
    active = await db().fetchval("UPDATE inventory_categories SET is_active=NOT is_active,updated_at=NOW() WHERE id=$1 RETURNING is_active", cat_id)
    await cb.answer("Category enabled." if active else "Category disabled.", show_alert=True)


@router.callback_query(F.data == "admin:wallet_qr")
async def qr_upload_start(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True); return
    await state.set_state(WalletFSM.qr_upload)
    await cb.answer()
    await cb.message.answer("PhonePe QR ki image bhejein. Purana QR replace ho jayega. Cancel: /cancel")


@router.message(WalletFSM.qr_upload)
async def qr_upload_save(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        await state.clear(); return
    if msg.text and msg.text.strip() == "/cancel":
        await state.clear(); await msg.answer("QR update cancel.")
        return
    if not msg.photo:
        await msg.answer("QR ki photo bhejein. Cancel: /cancel"); return
    file_id = msg.photo[-1].file_id
    await db().execute("INSERT INTO bot_settings(key,value,updated_at) VALUES('phonepe_qr_file_id',$1,NOW()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=NOW()", file_id)
    await state.clear()
    await msg.answer("✅ PhonePe QR save ho gaya. Minimum deposit ₹25 hai.")


@router.callback_query(F.data == "admin:wallet_history")
async def history_start(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True); return
    await state.set_state(WalletFSM.history_search)
    await cb.answer()
    await cb.message.answer("User ka Telegram ID, username ya naam bhejein. Recent transactions ke liye ALL likhein. Cancel: /cancel")


@router.message(WalletFSM.history_search, F.text)
async def history_search(msg: Message, state: FSMContext):
    if not await is_admin(msg.from_user.id):
        await state.clear(); return
    query = (msg.text or "").strip()
    if query == "/cancel":
        await state.clear(); await msg.answer("Cancelled."); return
    if query.upper() == "ALL":
        rows = await db().fetch("""SELECT t.*,u.full_name,u.username FROM wallet_transactions t JOIN users u ON u.telegram_id=t.user_id ORDER BY t.id DESC LIMIT 30""")
    else:
        uid = int(query) if query.isdigit() else -1
        rows = await db().fetch("""SELECT t.*,u.full_name,u.username FROM wallet_transactions t JOIN users u ON u.telegram_id=t.user_id
            WHERE u.telegram_id=$1 OR COALESCE(u.username,'') ILIKE $2 OR COALESCE(u.full_name,'') ILIKE $2
            ORDER BY t.id DESC LIMIT 30""", uid, "%" + query.lstrip("@") + "%")
    await state.clear()
    if not rows:
        await msg.answer("Is user ke transaction nahi mile.")
        return
    text = "🧾 <b>Transaction History</b> (latest 30)\n"
    for r in rows:
        text += "\n#" + str(r["id"]) + " | " + (r["full_name"] or "Unknown") + " | @" + (r["username"] or "—") + "\nUser ID: <code>" + str(r["user_id"]) + "</code>\nType: " + r["kind"] + " | Amount: " + money(r["amount_paise"]) + "\nBalance after: " + money(r["balance_after_paise"]) + "\nRef: <code>" + r["reference"][:45] + "</code>\nTime: " + str(r["created_at"]) + "\n"
    await msg.answer(text)
