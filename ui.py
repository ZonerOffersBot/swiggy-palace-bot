from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def main_menu():
    return InlineKeyboardMarkup([
      [InlineKeyboardButton("🛒 Place New Order",callback_data="new_order")],
      [InlineKeyboardButton("⭐ Become High Priority",callback_data="priority")],
      [InlineKeyboardButton("📦 My Orders",callback_data="my_orders"),InlineKeyboardButton("👤 My Profile",callback_data="profile")],
      [InlineKeyboardButton("💬 Help & Tutorial",callback_data="help"),InlineKeyboardButton("🎫 Support",callback_data="ticket")]
    ])

def admin_menu():
    return InlineKeyboardMarkup([
      [InlineKeyboardButton("📥 New Orders",callback_data="a_new"),InlineKeyboardButton("💳 Payments",callback_data="a_pay")],
      [InlineKeyboardButton("📦 Active Orders",callback_data="a_active"),InlineKeyboardButton("📊 Stats",callback_data="a_stats")],
      [InlineKeyboardButton("👨‍💼 Admins",callback_data="a_admins"),InlineKeyboardButton("💰 Charges",callback_data="a_charges")],
      [InlineKeyboardButton("🔳 QR Settings",callback_data="a_qr"),InlineKeyboardButton("⚙️ Settings",callback_data="a_settings")]
    ])

def order_actions(oid):
    return InlineKeyboardMarkup([
      [InlineKeyboardButton("💳 Payment",callback_data=f"pay:{oid}"),InlineKeyboardButton("📍 Request Address",callback_data=f"reqaddr:{oid}")],
      [InlineKeyboardButton("🛒 Request Cart",callback_data=f"reqcart:{oid}")],
      [InlineKeyboardButton("✅ Mark Placed",callback_data=f"placed:{oid}"),InlineKeyboardButton("🏁 Complete",callback_data=f"complete:{oid}")],
      [InlineKeyboardButton("↩️ Refund",callback_data=f"refund:{oid}")]
    ])
