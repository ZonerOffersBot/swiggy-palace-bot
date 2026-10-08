import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import (
    ADMIN_IDS, STATE_AWAITING_UTR, STATE_AWAITING_SCREENSHOT, 
    STATE_AWAITING_ADDRESS, STATE_AWAITING_PRICE, STATE_AWAITING_SWIGGY_ID
)
from db import (
    upsert_user, get_user, get_order, get_customer_orders, get_pending_orders, 
    create_order_safe, update_order_safe, audit, fetch_one, setting
)

logger = logging.getLogger(__name__)

# --- Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("⚠️ A temporary error occurred. Our team is looking into it. Please try again.")

# --- Helper: Restore Customer Order State ---
async def restore_order_state(update: Update, context: ContextTypes.DEFAULT_TYPE, order: dict):
    context.user_data['current_order'] = order['id']
    status = order['status']
    
    if status == 'new':
        context.user_data['state'] = STATE_AWAITING_SCREENSHOT
        await update.effective_message.reply_text(f"▶️ Resuming Order `{order['id']}`.\nPlease upload your cart screenshot.", parse_mode="Markdown")
    elif status == 'payment_pending':
        context.user_data['state'] = STATE_AWAITING_UTR
        await update.effective_message.reply_text(f"▶️ Resuming Order `{order['id']}`.\nPlease send your Payment UTR / Reference Number.", parse_mode="Markdown")
    elif status == 'address_pending':
        context.user_data['state'] = STATE_AWAITING_ADDRESS
        await update.effective_message.reply_text(f"▶️ Resuming Order `{order['id']}`.\nPlease send your Delivery Address link.", parse_mode="Markdown")
    else:
        context.user_data['state'] = None
        await update.effective_message.reply_text(f"▶️ Order `{order['id']}` status: {status}. Waiting for Admin action.", parse_mode="Markdown")

# --- Core Commands ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await upsert_user(user)
    
    unfinished = await fetch_one(
        "SELECT id FROM orders WHERE customer_id=? AND status NOT IN ('completed', 'cancelled', 'refund_completed') ORDER BY created_at DESC LIMIT 1", 
        (user.id,)
    )
    
    keyboard = []
    if unfinished:
        keyboard.append([InlineKeyboardButton(f"▶️ Resume Order {unfinished['id']}", callback_data=f"resume_order:{unfinished['id']}")])
        keyboard.append([InlineKeyboardButton("🆕 Start New Order", callback_data="create_new_order_force")])
    else:
        keyboard.append([InlineKeyboardButton("🛒 Place New Order", callback_data="cust_new_order")])
        
    keyboard.append([InlineKeyboardButton("📦 My Orders", callback_data="cust_my_orders")])
    keyboard.append([InlineKeyboardButton("👤 My Profile", callback_data="cust_profile")])
    
    if user.id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="adm_panel")])
        
    await update.message.reply_text(
        f"Welcome to Swiggy Palace, {user.first_name}!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --- Central Callback Router ---
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    try:
        # ================= CUSTOMER FLOW =================
        if data.startswith("resume_order:"):
            oid = data.split(":")[1]
            order = await get_order(oid)
            if not order or order["customer_id"] != user_id:
                await query.edit_message_text("❌ Unauthorized or Order not found.")
                return
            await restore_order_state(update, context, dict(order))
            return

        if data in ("cust_new_order", "create_new_order_force"):
            if data == "cust_new_order":
                unfinished = await fetch_one(
                    "SELECT id FROM orders WHERE customer_id=? AND status NOT IN ('completed', 'cancelled', 'refund_completed') ORDER BY created_at DESC LIMIT 1", 
                    (user_id,)
                )
                if unfinished:
                    keyboard = [
                        [InlineKeyboardButton(f"▶️ Resume Order {unfinished['id']}", callback_data=f"resume_order:{unfinished['id']}")],
                        [InlineKeyboardButton("🆕 Start New Order Anyway", callback_data="create_new_order_force")]
                    ]
                    await query.edit_message_text(
                        f"⚠️ You already have an unfinished order `{unfinished['id']}`. Please resume it or start a new one.",
                        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
                    )
                    return

            oid = await create_order_safe(user_id, idempotency_key=f"new_{user_id}_{query.message.message_id}")
            await query.edit_message_text(f"Order created! ID: `{oid}`\nPlease upload your cart screenshot now.", parse_mode="Markdown")
            context.user_data['state'] = STATE_AWAITING_SCREENSHOT
            context.user_data['current_order'] = oid
            
        elif data == "cust_my_orders":
            orders = await get_customer_orders(user_id)
            if not orders:
                await query.edit_message_text("You have no orders yet.")
                return
            
            text = "📦 *Your Recent Orders:*\n\n"
            keyboard = []
            for o in orders:
                status_text = o['status'].replace('_', ' ').title()
                text += f"ID: `{o['id']}` | Status: {status_text} | Total: ₹{o['total']}\n"
                if o['status'] not in ('completed', 'cancelled', 'refund_completed'):
                    keyboard.append([InlineKeyboardButton(f"▶️ Resume {o['id']}", callback_data=f"resume_order:{o['id']}")])
            
            keyboard.append([InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")])
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif data == "back_to_menu":
            await start_command(update, context) # Or recreate the menu

        # ================= ADMIN FLOW =================
        elif data == "adm_panel" and user_id in ADMIN_IDS:
            await query.edit_message_text("⚙️ *Admin Panel*\nSelect an option:", 
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📥 New Orders", callback_data="adm_pending")],
                    [InlineKeyboardButton("💳 Verify Payments", callback_data="adm_payments")]
                ]), parse_mode="Markdown")
                                          
        elif data == "adm_pending" and user_id in ADMIN_IDS:
            orders = await get_pending_orders()
            if not orders:
                await query.edit_message_text("✅ No pending orders right now.")
                return
            
            keyboard = []
            for o in orders:
                # Button format: "Order SP-1000 | status"
                keyboard.append([InlineKeyboardButton(f"📦 {o['id']} | {o['status'].replace('_', ' ').title()}", callback_data=f"adm_view:{o['id']}")])
            keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="adm_panel")])
            
            await query.edit_message_text("📥 *Select an Order to Manage:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif data.startswith("adm_view:") and user_id in ADMIN_IDS:
            oid = data.split(":")[1]
            order = await get_order(oid)
            if not order:
                await query.edit_message_text("❌ Order not found.")
                return
                
            customer = await get_user(order['customer_id'])
            
            text = f"📦 *Order Details: {oid}*\n\n"
            text += f"👤 Customer: {customer['first_name']} (@{customer['username']})\n"
            text += f"📊 Status: {order['status'].replace('_', ' ').title()}\n"
            text += f"💰 Total: ₹{order['total']}\n"
            text += f"💳 Payment: {order['payment_status'].title()}\n"
            
            keyboard = [
                [InlineKeyboardButton("💰 Set Final Price", callback_data=f"adm_setprice:{oid}")],
                [InlineKeyboardButton("📍 Request Address", callback_data=f"adm_reqaddr:{oid}")],
                [InlineKeyboardButton("💳 Request Payment", callback_data=f"adm_pay:{oid}")],
                [InlineKeyboardButton("🧾 Set Swiggy Order ID", callback_data=f"adm_setid:{oid}")],
                [InlineKeyboardButton("✅ Mark Completed", callback_data=f"adm_complete:{oid}")],
                [InlineKeyboardButton("⬅️ Back to List", callback_data="adm_pending")]
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            
            # Send Cart Screenshot if exists
            if order['cart_screenshot']:
                try:
                    await query.message.reply_photo(photo=order['cart_screenshot'], caption=f"Cart Screenshot for {oid}")
                except Exception as e:
                    logger.error(f"Failed to send cart screenshot: {e}")

        # Admin Actions
        elif data.startswith("adm_setprice:") and user_id in ADMIN_IDS:
            oid = data.split(":")[1]
            context.user_data['state'] = STATE_AWAITING_PRICE
            context.user_data['admin_order'] = oid
            await query.edit_message_text(f"💰 Please enter the final Swiggy amount for Order `{oid}` (Numbers only):", parse_mode="Markdown")

        elif data.startswith("adm_setid:") and user_id in ADMIN_IDS:
            oid = data.split(":")[1]
            context.user_data['state'] = STATE_AWAITING_SWIGGY_ID
            context.user_data['admin_order'] = oid
            await query.edit_message_text(f"🧾 Please enter the Swiggy Order ID for Order `{oid}`:", parse_mode="Markdown")

        elif data.startswith("adm_reqaddr:") and user_id in ADMIN_IDS:
            oid = data.split(":")[1]
            order = await get_order(oid)
            await update_order_safe(oid, status="address_pending")
            # Notify customer
            try:
                await context.bot.send_message(
                    chat_id=order['customer_id'],
                    text=f"📍 Admin has requested your delivery address for Order `{oid}`.\nPlease reply with your address link.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to notify customer: {e}")
            await query.edit_message_text(f"✅ Address requested from customer for Order `{oid}`.", parse_mode="Markdown")

        elif data.startswith("adm_complete:") and user_id in ADMIN_IDS:
            oid = data.split(":")[1]
            await update_order_safe(oid, status="completed")
            order = await get_order(oid)
            try:
                await context.bot.send_message(chat_id=order['customer_id'], text=f"🎉 Your Order `{oid}` has been marked as Completed. Thank you!", parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Failed to notify customer: {e}")
            await query.edit_message_text(f"✅ Order `{oid}` marked as Completed.", parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Callback error: {e}", exc_info=True)
        await query.edit_message_text("⚠️ Error processing request.")

# --- Single Photo Handler ---
async def photo_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = context.user_data.get('state')
    photo_file_id = update.message.photo[-1].file_id
    
    try:
        if state == STATE_AWAITING_SCREENSHOT:
            oid = context.user_data.get('current_order')
            if not oid:
                await update.message.reply_text("❌ No active order found. Please /start again.")
                return
            await update_order_safe(oid, cart_screenshot=photo_file_id, status="cart_uploaded")
            await update.message.reply_text("✅ Cart screenshot received! Admin will verify shortly.")
            context.user_data['state'] = None
            
        else:
            await update.message.reply_text("📸 Photo received, but no active action is awaiting a photo.")
            
    except Exception as e:
        logger.error(f"Photo handler error: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Failed to process image.")

# --- Text Message Router ---
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('state')
    text = update.message.text
    user_id = update.effective_user.id
    
    try:
        # --- ADMIN TEXT INPUTS ---
        if user_id in ADMIN_IDS and state == STATE_AWAITING_PRICE:
            oid = context.user_data.get('admin_order')
            try:
                price = float(text)
                # Update order with price and add palace charge
                palace_charge = float(await setting("palace_charge", "30"))
                total = price + palace_charge
                await update_order_safe(oid, swiggy_amount=price, palace_charge=palace_charge, total=total, status="payment_pending")
                
                # Notify customer for payment
                order = await get_order(oid)
                await context.bot.send_message(
                    chat_id=order['customer_id'],
                    text=f"💰 Payment requested for Order `{oid}`.\nSwiggy Amount: ₹{price}\nPalace Charge: ₹{palace_charge}\n*Total: ₹{total}*\n\nPlease send the payment and reply with your UTR/Reference Number.",
                    parse_mode="Markdown"
                )
                await update.message.reply_text(f"✅ Price set for Order `{oid}`. Customer has been notified to pay ₹{total}.", parse_mode="Markdown")
            except ValueError:
                await update.message.reply_text("❌ Invalid input. Please enter a valid number (e.g., 450).")
                return
            context.user_data['state'] = None
            return

        if user_id in ADMIN_IDS and state == STATE_AWAITING_SWIGGY_ID:
            oid = context.user_data.get('admin_order')
            await update_order_safe(oid, swiggy_order_id=text, status="placed")
            await update.message.reply_text(f"✅ Swiggy Order ID `{text}` saved for Order `{oid}`.", parse_mode="Markdown")
            context.user_data['state'] = None
            return

        # --- CUSTOMER TEXT INPUTS ---
        if state == STATE_AWAITING_UTR:
            oid = context.user_data.get('current_order')
            if not oid:
                await update.message.reply_text("❌ No active order found. Please /start again.")
                return
            await update_order_safe(oid, payment_utr=text, payment_status="pending_verification")
            await update.message.reply_text("✅ UTR received! Awaiting admin verification.")
            context.user_data['state'] = None
            
        elif state == STATE_AWAITING_ADDRESS:
            oid = context.user_data.get('current_order')
            if not oid:
                # Try to find latest address_pending order
                order = await fetch_one("SELECT id FROM orders WHERE customer_id=? AND status='address_pending' ORDER BY created_at DESC LIMIT 1", (user_id,))
                if order:
                    oid = order['id']
                else:
                    await update.message.reply_text("❌ No active order found. Please /start again.")
                    return
            await update_order_safe(oid, address_link=text, status="address_received")
            await update.message.reply_text("✅ Address received! Admin will process your order.")
            context.user_data['state'] = None
            
        else:
            await update.message.reply_text("I didn't understand that. Use /start to see the menu.")
    except Exception as e:
        logger.error(f"Text handler error: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Error processing text.")
