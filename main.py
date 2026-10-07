import asyncio, logging, os
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from config import BOT_TOKEN, ADMIN_IDS, OWNER_ID, PORT
import db
from ui import main_menu, admin_menu, order_actions, role_menu

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log=logging.getLogger("swiggy-palace")

# Per-user short-lived input state. Durable business state is kept in SQLite.
state={}

async def is_admin(uid):
    if uid==OWNER_ID or uid in ADMIN_IDS:
        return True
    try:
        return await db.is_db_admin(uid)
    except Exception:
        return False

FORCE_JOIN_CHANNEL="@Swiggypalace"

async def force_join_required(uid):
    dbx=await db.connect()
    try:
        cur=await dbx.execute("SELECT value FROM settings WHERE key='force_join_channels'")
        row=await cur.fetchone()
        channels=(row["value"].split(",") if row and row["value"] else [FORCE_JOIN_CHANNEL])
        cur=await dbx.execute("SELECT value FROM settings WHERE key='force_join_verified'")
        verified=await cur.fetchone()
        ids=set((verified["value"] if verified else "").split(","))
        if str(uid) in ids:
            return False
        for ch in channels:
            ch=ch.strip()
            if not ch: continue
            try:
                m=await app_global.bot.get_chat_member(ch,uid)
                if m.status in ("creator","administrator","member") or (m.status=="restricted" and getattr(m,"is_member",False)):
                    continue
                return True
            except Exception:
                return True
        return False
    finally:
        await dbx.close()

async def mark_force_join_verified(uid):
    dbx=await db.connect()
    cur=await dbx.execute("SELECT value FROM settings WHERE key='force_join_verified'")
    row=await cur.fetchone()
    ids=[x for x in (row["value"] if row else "").split(",") if x and x!=str(uid)]
    ids.append(str(uid))
    await dbx.execute("INSERT INTO settings(key,value) VALUES('force_join_verified,',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(",".join(ids),))
    # Correct the key if SQLite inserted the typo-safe statement above.
    await dbx.execute("INSERT INTO settings(key,value) VALUES('force_join_verified',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(",".join(ids),))
    await dbx.commit(); await dbx.close()

async def show_force_join(target):
    kb=InlineKeyboardMarkup([
      [InlineKeyboardButton("📢 Join Swiggy Palace",url="https://t.me/Swiggypalace")],
      [InlineKeyboardButton("✅ I Joined",callback_data="force_join_check")]
    ])
    await target.reply_text(
      "🏰 <b>SWIGGY PALACE</b> 👑\n\n"
      "🔒 <b>Join Required</b>\n\n"
      "Bot use karne se pehle hamare official channel ko join karein:\n"
      "📢 @Swiggypalace\n\n"
      "1️⃣ Channel join karein\n2️⃣ <b>✅ I Joined</b> dabayein\n3️⃣ Verification ke baad menu open hoga.",
      parse_mode="HTML",reply_markup=kb)

async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    u=update.effective_user
    await db.upsert_user(u)
    state.pop(u.id,None)
    await update.message.reply_text(
      "🏰 <b>SWIGGY PALACE</b> 👑\n\n"
      "🍔 <b>Manual Swiggy Ordering Service</b>\n\n"
      "Safe & reliable manual ordering support.\n"
      "Aap apni need ke hisaab se Customer ya Seller choose karein.\n\n"
      "🛒 <b>Become a Customer</b>\n"
      "💸 Low-price food ordering support\n"
      "📍 Address + cart share karein\n"
      "💳 Final price verification ke baad payment\n"
      "👨‍💼 Order manually Palace Admin place karega\n"
      "📦 Order status aur Swiggy Order ID updates\n\n"
      "🏪 <b>Become a Seller</b>\n"
      "🤝 Swiggy Palace ke saath seller ke roop me judhein\n"
      "🏰 Seller approval ke baad Mini Admin access\n"
      "🛡️ Safe & reliable process\n"
      "📱 Customers/orders ko manage karne ke liye Palace ke andar hi tools\n"
      "💯 Bot-side commission: <b>₹0</b>\n"
      "🚫 Idhar-udhar alag service dhoondhne ki zarurat nahi\n"
      "🔔 Seller request direct Super Admin approval ke liye jayegi.\n\n"
      "👇 <b>Choose your role:</b>",
      parse_mode="HTML",reply_markup=role_menu())


async def addadmin_cmd(update,context):
    if update.effective_user.id!=OWNER_ID:
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("➕ Usage: /addadmin TELEGRAM_ID ROLE Name")
        return
    aid=int(context.args[0])
    role=context.args[1] if len(context.args)>1 else "order_admin"
    name=" ".join(context.args[2:]) if len(context.args)>2 else ""
    await db.add_admin(aid,role,name)
    await update.message.reply_text(f"✅ Admin added\\n🆔 {aid}\\n👤 Role: {role}\\n📛 Name: {name or '-'}")

async def removeadmin_cmd(update,context):
    if update.effective_user.id!=OWNER_ID:
        return
    if not context.args or not context.args[0].isdigit():
        return
    aid=int(context.args[0])
    if aid==OWNER_ID:
        await update.message.reply_text("❌ Owner ko remove nahi kiya ja sakta.")
        return
    await db.remove_admin(int(context.args[0]))
    await update.message.reply_text(f"🗑️ Admin removed: {aid}")

async def admin_cmd(update,context):
    if not await is_admin(update.effective_user.id): return
    await update.message.reply_text("👑 <b>Swiggy Palace Admin Panel</b>",parse_mode="HTML",reply_markup=admin_menu())

async def callbacks(update:Update,context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); uid=q.from_user.id; data=q.data
    if data=="force_join_check":
        if await force_join_required(uid):
            await q.message.reply_text("❌ Pehle @Swiggypalace channel join karein, phir ✅ I Joined dabayein.")
            return
        await mark_force_join_verified(uid)
        await q.message.edit_text("✅ <b>Verification Complete!</b>\n\n🏰 Welcome to Swiggy Palace.\n👇 Ab apna role choose karein.",parse_mode="HTML",reply_markup=role_menu())
        return
    if data=="become_customer":
        await db.assign_public_id(uid,"customer")
        await q.message.edit_text(
          "🛒 <b>BECOME A CUSTOMER</b>\n\n"
          "🍔 Swiggy food ko simple manual ordering support ke saath order karein.\n"
          "💸 Low-price food offers/order support\n"
          "🛡️ Safe & reliable process\n"
          "📍 Address + cart + screenshot share karein\n"
          "💳 Final amount verify hone ke baad payment karein\n"
          "👨‍💼 Order Palace Admin manually place karega\n\n"
          "👇 Customer menu:",
          parse_mode="HTML",reply_markup=main_menu())
        return
    if data=="become_seller":
        await q.message.edit_text(
          "🏪 <b>BECOME A SELLER</b>\n\n"
          "Swiggy Palace Seller banne ke fayde:\n\n"
          "🤝 Palace ke saath directly kaam karein\n"
          "🛡️ Safe & reliable managed process\n"
          "📱 Customer/order management tools ek hi jagah\n"
          "🏰 Approval ke baad <b>Mini Admin</b> access\n"
          "💯 <b>Bot-side commission: ₹0</b>\n"
          "🚫 Idhar-udhar alag service dhoondhne ki zarurat nahi\n"
          "🔔 Seller request direct Super Admin ko approval ke liye jayegi.\n\n"
          "⚠️ Seller approval ke baad hi Mini Admin access activate hoga.",
          parse_mode="HTML",
          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back",callback_data="start_roles")]])
        )
        return
    if data=="start_roles":
        await q.message.edit_text(
          "🏰 <b>SWIGGY PALACE</b> 👑\n\n👇 <b>Choose your role:</b>",
          parse_mode="HTML",reply_markup=role_menu())
        return
    if data=="new_order":
        active=await db.has_unfinished_order(uid)
        if active:
            fee=await db.second_order_fee()
            unlock=await db.has_second_order_unlock(uid)
            if not unlock:
                qr,_=await db.payment_qr_for(uid)
                msg=(f"🔒 <b>NEW ORDER LOCKED</b>\n\n"
                     f"🆔 Current Order: <code>{active['id']}</code>\n"
                     f"📌 Status: {active['status']}\n\n"
                     f"Ek active order already hai. 2nd order ke liye pehle <b>Palace Charge ₹{fee:.0f}</b> advance pay karna hoga.\n\n"
                     "💳 QR par payment karo → UTR bhejo → screenshot bhejo.\n"
                     "Payment verify hone ke baad New Order unlock hoga.")
                kb=InlineKeyboardMarkup([[InlineKeyboardButton(f"💳 Pay 2nd Order Charge ₹{fee:.0f}",callback_data="second_order_pay")]])
                if qr:
                    try:
                        await q.message.reply_photo(qr,caption=msg,parse_mode="HTML",reply_markup=kb)
                    except Exception:
                        await q.message.reply_text(msg+f"\n\n🔳 QR: {qr}",parse_mode="HTML",reply_markup=kb)
                else:
                    await q.message.reply_text(msg+"\n\n⚠️ QR configured nahi hai.",parse_mode="HTML",reply_markup=kb)
                return
            await q.message.reply_text(

              f"⚠️ <b>Aapka ek order already active hai.</b>\n\n"
              f"🆔 Current Order: <code>{active['id']}</code>\n"
              f"📌 Status: {active['status']}\n\n"
              "Ek time par sirf ek active order allowed hai.\n"
              "2nd order unlock charge verified hai. Aap next order flow continue kar sakte ho.",
              parse_mode="HTML")
            return
        oid=await db.create_order(uid); state[uid]={"action":"address","oid":oid}
        await q.message.reply_text(f"🛒 <b>{oid}</b> created.\n\n📍 Ab apna <b>Swiggy Address Link</b> bhejo.",parse_mode="HTML")
    elif data=="second_order_pay":
        fee=await db.second_order_fee()
        qr,aid=await db.payment_qr_for(uid)
        if not qr:
            await q.message.reply_text(f"🔒 <b>2nd Order Unlock</b>\n\nAdvance Palace Charge: ₹{fee:.0f}\n⚠️ Assigned Admin ka QR configured nahi hai.",parse_mode="HTML")
            return
        state[uid]={"action":"second_order_utr","fee":fee,"admin_id":aid}
        msg=(f"🔓 <b>2ND ORDER UNLOCK</b>\n\n💰 Advance Palace Charge: ₹{fee:.0f}\n\n"
             "1️⃣ QR par payment karo\n2️⃣ UTR number bhejo\n3️⃣ Payment screenshot bhejo\n\n"
             "🔒 Proof sirf aapke assigned Admin ko jayega.")
        try: await q.message.reply_photo(qr,caption=msg,parse_mode="HTML")
        except Exception: await q.message.reply_text(msg+f"\n\n🔳 QR: {qr}",parse_mode="HTML")
    elif data=="priority":
        fee=float(await db.setting("priority_fee","49"))
        aid=await db.assign_customer_admin(uid)
        qr,_=await db.payment_qr_for(uid)
        if not qr:
            await q.message.reply_text(
              "⭐ <b>High Priority</b>\n\n"
              f"💰 Advance: ₹{fee:.0f}\n"
              "⚠️ Payment QR abhi configured nahi hai. Admin QR set hone ke baad payment start hoga.",
              parse_mode="HTML")
            return
        state[uid]={"action":"priority_utr","fee":fee,"admin_id":aid}
        msg=(f"⭐ <b>HIGH PRIORITY</b>\n\n💰 Advance: ₹{fee:.0f}\n"
             f"⏱️ Assignment SLA: {await db.setting('priority_sla_minutes','5')} min\n"
             "⚠️ Priority means faster processing, not a guaranteed instant order.\n\n"
             "1️⃣ <b>QR par payment karo</b>\n"
             "2️⃣ Payment ka <b>UTR number</b> bhejo\n"
             "3️⃣ Uske baad <b>payment screenshot</b> upload karo.\n\n"
             "🔒 Screenshot sirf aapke assigned Palace Admin ko jayega.")
        try:
            await q.message.reply_photo(qr,caption=msg,parse_mode="HTML")
        except Exception:
            await q.message.reply_text(msg+f"\n\n🔳 QR: {qr}",parse_mode="HTML")
    elif data=="my_orders":
        dbx=await db.connect(); cur=await dbx.execute("SELECT id,status,total FROM orders WHERE customer_id=? ORDER BY created_at DESC LIMIT 10",(uid,)); rows=await cur.fetchall(); await dbx.close()
        text="📦 <b>My Orders</b>\n\n"+("\n".join(f"🆔 {r['id']} • {r['status']} • ₹{r['total']:.0f}" for r in rows) if rows else "No orders yet.")
        await q.message.reply_text(text,parse_mode="HTML")
    elif data=="profile":
        dbx=await db.connect(); cur=await dbx.execute("SELECT * FROM users WHERE id=?",(uid,)); r=await cur.fetchone(); await dbx.close()
        await q.message.reply_text(f"👤 <b>Profile</b>\n⭐ Rating: {(r['rating_sum']/r['rating_count'] if r['rating_count'] else 0):.1f}\n⚠️ Warnings: {r['warnings']}\n📦 Orders: use My Orders",parse_mode="HTML")
    elif data=="help":
        await q.message.reply_text("📖 <b>How it works</b>\n\n1️⃣ Place New Order\n2️⃣ 📍 Address link\n3️⃣ 🛒 Cart link\n4️⃣ 📸 Cart screenshot\n5️⃣ 💰 Palace gives final price\n6️⃣ 💳 Pay + UTR/proof\n7️⃣ ✅ Payment is manually verified\n8️⃣ 👨‍💼 Admin manually places Swiggy order\n9️⃣ 📦 Swiggy Order ID/status shared\n🔟 🏁 Completion + feedback",parse_mode="HTML")
    elif data=="help_support" or data=="ticket":
        state[uid]={"action":"ticket_subject"}
        await q.message.reply_text("🆘 <b>Help & Support</b>\n\nApni query/problem ek message me likho.\nAapki query Ticket ID aur unique ID ke saath Owner ko milegi.",parse_mode="HTML")
    elif data.startswith("orderview:") or data.startswith("userview:"):
        await admin_callback(q,context,data)
    elif data=="qr_upload":
        if uid!=OWNER_ID:
            return
        state[uid]={"action":"qr_upload"}
        await q.message.reply_text(
          "📤 <b>UPLOAD PALACE QR</b>\n\n"
          "Ab apna QR code <b>photo</b> ke roop me bhejo.\n"
          "Photo milte hi Default Palace QR save ho jayega.\n\n"
          "💡 QR image ke saath caption dena zaroori nahi hai.",
          parse_mode="HTML")
    elif data.startswith("qr_admin:"):
        if uid!=OWNER_ID:
            return
        aid=int(data.split(":",1)[1])
        a=await db.get_admin(aid)
        if not a:
            await q.message.reply_text("❌ Admin not found.")
            return
        state[uid]={"action":"qr_admin_upload","admin_id":aid}
        await q.message.reply_text(
          f"📤 <b>UPLOAD QR — {a['display_name'] or aid}</b>\n\n"
          "Ab is Admin ka QR code photo bhejo.\n"
          "Payment screens par is assigned Admin ka QR use hoga.",
          parse_mode="HTML")
    elif data=="qr_remove_default":
        if uid!=OWNER_ID:
            return
        await db.set_setting("default_qr","")
        await q.message.reply_text("🗑️ Default Palace QR removed.")
    elif data.startswith("pay:"):
        oid=data.split(":",1)[1]; o=await db.get_order(oid)
        if not o or o["customer_id"]!=uid: return
        qr,_=await db.payment_qr_for(uid,oid)
        if not qr:
            await q.message.reply_text(
              f"💳 <b>{oid}</b>\n\n"
              f"Total payable: ₹{o['total']:.2f}\n"
              "⚠️ Payment QR abhi configured nahi hai. Assigned Admin ko QR set karna hoga.",
              parse_mode="HTML")
            return
        state[uid]={"action":"payment_utr","oid":oid}
        msg=(f"💳 <b>{oid} PAYMENT</b>\n\n"
             f"💰 Total payable: ₹{o['total']:.2f}\n\n"
             "1️⃣ <b>QR par payment karo</b>\n"
             "2️⃣ Payment ka <b>UTR number</b> bhejo\n"
             "3️⃣ Uske baad <b>payment screenshot</b> upload karo.\n\n"
             "🔒 Screenshot sirf aapke assigned Palace Admin ko jayega.")
        try:
            await q.message.reply_photo(qr,caption=msg,parse_mode="HTML")
        except Exception:
            await q.message.reply_text(msg+f"\n\n🔳 QR: {qr}",parse_mode="HTML")
    elif data.startswith("orderview:") or data.startswith("userview:") or data.startswith("a_") or data.startswith("approvepay:") or data.startswith("rejectpay:") or data.startswith("placed:") or data.startswith("complete:") or data.startswith("refund:") or data.startswith("reqaddr:") or data.startswith("reqcart:"):
        await admin_callback(q,context,data)
    elif data.startswith("prioapprove:") or data.startswith("prioreject:"):
        await admin_priority_callback(q,data)

async def admin_callback(q,context,data):
    uid=q.from_user.id
    if not await is_admin(uid): return
    if data=="a_stats":
        s=await db.stats(); await q.message.reply_text(f"📊 <b>Palace Stats</b>\n👥 Customers: {s['customers']}\n📦 Orders: {s['orders']}\n🏁 Completed: {s['completed']}\n⏳ Active: {s['active']}\n🍔 Swiggy Value: ₹{s['swiggy']:.2f}\n💰 Palace Charges: ₹{s['charges']:.2f}\n↩️ Refunds: ₹{s['refunds']:.2f}",parse_mode="HTML")
    elif data=="a_new":
        dbx=await db.connect(); cur=await dbx.execute("SELECT id FROM orders WHERE status IN ('new','address_received','cart_received','screenshot_received','price_confirmed') ORDER BY priority DESC,created_at ASC LIMIT 20"); rows=await cur.fetchall(); await dbx.close()
        if not rows:
            await q.message.reply_text("📥 <b>NEW ORDERS</b>\n\nNo new orders.",parse_mode="HTML"); return
        kb=[[InlineKeyboardButton(f"🆔 {o['id']}",callback_data=f"orderview:{o['id']}")] for o in rows]
        kb += [[InlineKeyboardButton("🔄 Refresh",callback_data="a_new"),InlineKeyboardButton("⬅️ Back",callback_data="a_back")]]
        await q.message.reply_text("📥 <b>NEW ORDERS</b>\n\nTap an Order ID to view details.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("orderview:"):
        oid=data.split(":",1)[1]
        o=await db.get_order(oid)
        if not o:
            await q.message.reply_text("❌ Order not found.")
            return
        if uid!=OWNER_ID and o["assigned_admin"] and int(o["assigned_admin"])!=uid:
            await q.message.reply_text("🔒 Ye order kisi aur Admin ko assigned hai.")
            return
        customer=await db.get_user(int(o["customer_id"]))
        assigned=await db.get_admin(int(o["assigned_admin"])) if o["assigned_admin"] else None
        assigned_name=(assigned["display_name"] or str(o["assigned_admin"])) if assigned else "Unassigned"
        msg=(f"📦 <b>ORDER DETAILS</b>\n\n"
             f"🆔 <code>{o['id']}</code>\n"
             f"👤 Customer: <code>{o['customer_id']}</code>\n"
             f"🪪 Customer ID: <code>{customer['public_id'] if customer and customer['public_id'] else '-'}</code>\n"
             f"👨‍💼 Assigned Admin: <b>{assigned_name}</b>\n"
             f"📌 Status: <b>{o['status']}</b>\n"
             f"🍔 Swiggy Amount: ₹{o['swiggy_amount']:.2f}\n"
             f"🏰 Palace Charge: ₹{o['palace_charge']:.2f}\n"
             f"⭐ Priority Fee: ₹{o['priority_fee']:.2f}\n"
             f"💳 Total: ₹{o['total']:.2f}\n"
             f"💰 Payment: <b>{o['payment_status']}</b>\n"
             f"🧾 Swiggy Order ID: {o['swiggy_order_id'] or '-'}\n\n"
             f"📍 Address: {o['address_link'] or '-'}\n"
             f"🛒 Cart: {o['cart_link'] or '-'}")
        kb=order_actions(oid).inline_keyboard
        kb.insert(0,[InlineKeyboardButton("👤 Open Customer",callback_data=f"userview:{o['customer_id']}")])
        await q.message.reply_text(msg,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("userview:"):
        cid=int(data.split(":",1)[1])
        customer=await db.get_user(cid)
        if not customer:
            await q.message.reply_text("❌ Customer not found.")
            return
        if uid!=OWNER_ID:
            assigned=await db.get_customer_admin(cid)
            if assigned and int(assigned)!=uid:
                await q.message.reply_text("🔒 Ye customer kisi aur Admin ko assigned hai.")
                return
        dbx=await db.connect()
        cur=await dbx.execute("SELECT COUNT(*) AS n FROM orders WHERE customer_id=?",(cid,))
        count=(await cur.fetchone())["n"]
        cur=await dbx.execute("SELECT id,status,total FROM orders WHERE customer_id=? ORDER BY created_at DESC LIMIT 10",(cid,))
        orders=await cur.fetchall()
        await dbx.close()
        pid=customer["public_id"] or "-"
        name=customer["first_name"] or customer["username"] or str(cid)
        rating=(customer["rating_sum"]/customer["rating_count"] if customer["rating_count"] else 0)
        lines=[f"👤 <b>CUSTOMER DETAILS</b>","",f"🪪 Customer ID: <code>{pid}</code>",f"🆔 Telegram ID: <code>{cid}</code>",f"👤 Name: {name}",f"⭐ Rating: {rating:.1f}",f"⚠️ Warnings: {customer['warnings']}",f"📦 Total Orders: {count}",""]
        if orders:
            lines.append("<b>Recent Orders</b>")
            lines.extend([f"• <code>{x['id']}</code> — {x['status']} — ₹{x['total']:.0f}" for x in orders])
        back=f"orderview:{orders[0]['id']}" if orders else "a_new"
        await q.message.reply_text("\n".join(lines),parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Order",callback_data=back)]]))
    elif data=="a_pay":
        dbx=await db.connect(); cur=await dbx.execute("SELECT o.*,p.utr,p.proof FROM orders o JOIN payments p ON p.order_id=o.id WHERE p.status='pending' ORDER BY o.created_at ASC LIMIT 20"); rows=await cur.fetchall(); await dbx.close()
        if not rows: await q.message.reply_text("💳 No pending payment verification."); return
        for o in rows:
            kb=[[__import__('telegram').InlineKeyboardButton("✅ Approve",callback_data=f"approvepay:{o['id']}"),__import__('telegram').InlineKeyboardButton("❌ Reject",callback_data=f"rejectpay:{o['id']}")]]
            await q.message.reply_text(f"💳 <b>{o['id']}</b>\n💰 ₹{o['total']:.2f}\nUTR: {o['utr']}",parse_mode="HTML",reply_markup=__import__('telegram').InlineKeyboardMarkup(kb))
    elif data=="a_active":
        dbx=await db.connect(); cur=await dbx.execute("SELECT id FROM orders WHERE status NOT IN ('completed','cancelled','refund_completed') ORDER BY priority DESC,updated_at DESC LIMIT 20"); rows=await cur.fetchall(); await dbx.close()
        if not rows:
            await q.message.reply_text("📦 <b>ONGOING ORDERS</b>\n\nNo ongoing orders.",parse_mode="HTML"); return
        kb=[[InlineKeyboardButton(f"🆔 {o['id']}",callback_data=f"orderview:{o['id']}")] for o in rows]
        kb += [[InlineKeyboardButton("🔄 Refresh",callback_data="a_active"),InlineKeyboardButton("⬅️ Back",callback_data="a_back")]]
        await q.message.reply_text("📦 <b>ONGOING ORDERS</b>\n\nTap an Order ID to view details.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))
    elif data=="a_admins":
        if uid!=OWNER_ID:
            await q.message.reply_text("🔒 Sirf Super Admin Owner hi Admin management kar sakta hai.")
            return
        rows=await db.list_admins()
        lines=["👨‍💼 <b>ADMIN MANAGEMENT</b>",""]
        if rows:
            for a in rows:
                name=f" — {a['display_name']}" if a['display_name'] else ""
                lines.append(f"🆔 <code>{a['id']}</code> • {a['role']}{name}")
        else:
            lines.append("No admins configured.")
        lines += ["","➕ <b>Add Admin</b> ke liye use karein:","<code>/addadmin TELEGRAM_ID ROLE Name</code>","Example: <code>/addadmin 123456789 order_admin Rahul</code>","", "🗑️ Remove: <code>/removeadmin TELEGRAM_ID</code>"]
        await q.message.reply_text("\n".join(lines),parse_mode="HTML")
    elif data=="a_charges":
        c=await db.setting("palace_charge","30"); enabled=await db.setting("palace_charge_enabled","1"); pf=await db.setting("priority_fee","49")
        await q.message.reply_text(f"💰 Charge ON: {enabled}\n🏰 Palace charge: ₹{c}\n⭐ Priority fee: ₹{pf}\n\nUse /setcharge amount and /setpriority amount.")
    elif data=="a_qr":
        if uid!=OWNER_ID:
            await q.message.reply_text("🔒 Sirf Super Admin Owner QR settings manage kar sakta hai.")
            return
        qr=await db.setting("default_qr","")
        rows=await db.list_admins()
        kb=[
          [InlineKeyboardButton("📤 Upload Default QR Photo",callback_data="qr_upload")],
          [InlineKeyboardButton("🗑️ Remove Default QR",callback_data="qr_remove_default")]
        ]
        for a in rows:
            kb.append([InlineKeyboardButton(f"🔳 Set QR — {a['display_name'] or a['id']}",callback_data=f"qr_admin:{a['id']}")])
        await q.message.reply_text(
          "🔳 <b>QR SETTINGS</b>\n\n"
          f"Default QR: {'✅ Configured' if qr else '❌ Not configured'}\n\n"
          "📤 Default QR photo upload karein, ya kisi Admin ke liye alag QR set karein.",
          parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))
    elif data=="a_settings":
        await q.message.reply_text("⚙️ Settings\n/setcharge 30\n/setpriority 49\n/setbusiness on|off\n/setqr VALUE")
    elif data.startswith("approvepay:"):
        await approve_payment(q,data.split(":")[1],True)
    elif data.startswith("rejectpay:"):
        await approve_payment(q,data.split(":")[1],False)
    elif data.startswith("placed:"):
        oid=data.split(":")[1]; await db.update_order(oid,status="order_placed"); o=await db.get_order(oid)
        await q.message.reply_text(f"📦 {oid} marked Order Placed.\n🧾 Ab Swiggy Order ID enter karne ke liye /swiggyid {oid} <ID>")
        try: await context.bot.send_message(o["customer_id"],f"📦 <b>{oid}</b>\n✅ Your Swiggy order has been placed manually by Palace Admin.",parse_mode="HTML")
        except: pass
    elif data.startswith("complete:"):
        oid=data.split(":")[1]; await db.update_order(oid,status="completed"); o=await db.get_order(oid)
        await q.message.reply_text(f"🏁 {oid} completed. Customer feedback can now be requested.")
        try: await context.bot.send_message(o["customer_id"],f"🏁 <b>{oid}</b> completed! ⭐ Please use /feedback {oid} to rate your experience.",parse_mode="HTML")
        except: pass
    elif data.startswith("refund:"):
        oid=data.split(":")[1]; o=await db.get_order(oid); dbx=await db.connect()
        await dbx.execute("INSERT OR IGNORE INTO refunds(order_id,amount,reason,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",(oid,o["total"],"Admin requested", "pending",db.now(),db.now())); await dbx.commit(); await dbx.close()
        await db.update_order(oid,status="refund_pending"); await q.message.reply_text(f"↩️ Refund Pending for {oid}. Manual refund required.")
    elif data.startswith("reqaddr:") or data.startswith("reqcart:"):
        oid=data.split(":")[1]; kind="address" if data.startswith("reqaddr") else "cart"; o=await db.get_order(oid)
        state[o["customer_id"]]={"action":kind,"oid":oid}; await q.message.reply_text(f"📨 Customer asked for a new {kind} link.")
        try: await context.bot.send_message(o["customer_id"],f"🔄 Please send a new Swiggy {kind} link for <b>{oid}</b>.",parse_mode="HTML")
        except: pass

async def approve_payment(q,oid,ok):
    o=await db.get_order(oid)
    if not o: return
    dbx=await db.connect()
    await dbx.execute("UPDATE payments SET status=?,verified_by=?,updated_at=? WHERE order_id=?",("verified" if ok else "rejected",q.from_user.id,db.now(),oid))
    await dbx.commit(); await dbx.close()
    await db.update_order(oid,payment_status="verified" if ok else "rejected",status="ready_to_place" if ok else "price_confirmed")
    await q.message.reply_text(("✅ Payment approved." if ok else "❌ Payment rejected.")+f" {oid}")

async def admin_priority_callback(q,data):
    if not await is_admin(q.from_user.id): return
    uid=int(data.split(":")[1]); dbx=await db.connect()
    ok=data.startswith("prioapprove:")
    await dbx.execute("UPDATE priority_payments SET status=?,verified_by=? WHERE customer_id=? AND status='pending'",("verified" if ok else "rejected",q.from_user.id,uid))
    await dbx.execute("UPDATE users SET priority=?,priority_paid=? WHERE id=?",(1 if ok else 0,1 if ok else 0,uid))
    await dbx.commit(); await dbx.close(); await q.message.reply_text("⭐ Priority "+("activated." if ok else "rejected."))

async def text_handler(update:Update,context:ContextTypes.DEFAULT_TYPE):
    u=update.effective_user; uid=u.id; await db.upsert_user(u); s=state.get(uid); text=update.message.text
    if not s: return
    action=s["action"]; oid=s.get("oid")
    if action in ("address","cart"):
        field="address_link" if action=="address" else "cart_link"
        await db.update_order(oid,**{field:text,"status":"address_received" if action=="address" else "cart_received"})
        if action=="address":
            state[uid]={"action":"cart","oid":oid}; await update.message.reply_text(f"🛒 {oid}: ab Swiggy cart link bhejo.")
        else:
            state[uid]={"action":"screenshot","oid":oid}; await update.message.reply_text(f"📸 {oid}: ab cart screenshot upload karo.")
    elif action=="ticket_subject":
        dbx=await db.connect(); cur=await dbx.execute("INSERT INTO tickets(customer_id,subject,created_at) VALUES(?,?,?)",(uid,text,db.now())); tid=cur.lastrowid; await dbx.execute("INSERT INTO ticket_messages(ticket_id,sender_id,body,created_at) VALUES(?,?,?,?)",(tid,uid,text,db.now())); await dbx.commit(); await dbx.close(); state.pop(uid,None)
        await update.message.reply_text(f"🎫 Ticket #{tid} created. Support team will reply.")
        for aid in ADMIN_IDS:
            try: await context.bot.send_message(aid,f"🎫 New support ticket #{tid} from {uid}: {text}")
            except: pass
    elif action=="payment_utr":
        await db.update_order(oid,payment_utr=text); dbx=await db.connect(); await dbx.execute("INSERT OR REPLACE INTO payments(order_id,utr,amount,created_at,updated_at) VALUES(?,?,?,?,?)",(oid,text,(await db.get_order(oid))["total"],db.now(),db.now())); await dbx.commit(); await dbx.close()
        state[uid]={"action":"payment_proof","oid":oid}; await update.message.reply_text("📸 UTR saved. Ab payment screenshot bhejo.\n🔒 Screenshot sirf aapke assigned Admin ko jayega.")
    elif action=="second_order_utr":
        state[uid]={"action":"second_order_proof","utr":text,"fee":s["fee"],"admin_id":s.get("admin_id",0)}
        await update.message.reply_text("📸 UTR saved. Ab 2nd order unlock payment screenshot bhejo.")
    elif action=="priority_utr":
        state[uid]={"action":"priority_proof","utr":text,"fee":s["fee"],"admin_id":s.get("admin_id",0)}; await update.message.reply_text("📸 Priority payment screenshot bhejo.")
    elif action=="swiggyid":
        await db.update_order(oid,swiggy_order_id=text); state.pop(uid,None); await update.message.reply_text(f"🧾 {oid} Swiggy Order ID saved: {text}")

async def qr_photo_handler(update,context):
    uid=update.effective_user.id
    if uid!=OWNER_ID:
        return
    s=state.get(uid,{})
    caption=(update.message.caption or "").strip()
    fid=update.message.photo[-1].file_id
    if s.get("action")=="qr_admin_upload":
        aid=int(s["admin_id"])
        await db.set_admin_qr(aid,fid,True)
        state.pop(uid,None)
        await update.message.reply_text(f"✅ Admin QR saved successfully for Admin {aid}.")
        return
    if s.get("action")=="qr_upload" or caption.lower().startswith("/setqr"):
        await db.set_setting("default_qr",fid)
        state.pop(uid,None)
        await update.message.reply_text("✅ Default Palace QR image saved successfully.")

async def photo_handler(update,context):
    uid=update.effective_user.id; s=state.get(uid)
    if not s: return
    fid=update.message.photo[-1].file_id; action=s["action"]; oid=s.get("oid")
    if action=="screenshot":
        await db.update_order(oid,cart_screenshot=fid,status="screenshot_received"); state.pop(uid,None)
        await update.message.reply_text(f"📸 {oid} screenshot received. Palace Admin will verify cart and enter actual Swiggy price.")
        o=await db.get_order(oid); aid=int(o["assigned_admin"] or await db.get_customer_admin(uid) or OWNER_ID)
        if aid:
            try: await context.bot.send_message(aid,f"📥 New cart screenshot for {oid} from customer {uid}. Open Admin Panel with /admin.")
            except: pass
    elif action=="payment_proof":
        dbx=await db.connect(); await dbx.execute("UPDATE payments SET proof=?,status='pending',updated_at=? WHERE order_id=?",(fid,db.now(),oid)); await dbx.commit(); await dbx.close(); state.pop(uid,None)
        await update.message.reply_text(f"💳 Payment proof received for {oid}. Manual verification pending.")
        o=await db.get_order(oid); aid=int(o["assigned_admin"] or await db.get_customer_admin(uid) or OWNER_ID)
        if aid:
            try: await context.bot.send_photo(aid,fid,caption=f"💳 Payment pending: {oid}\nCustomer: {uid}\nUTR: {o['payment_utr'] or '-'}\n🔒 Assigned customer payment — Use /admin → Payments.")
            except: pass
    elif action=="second_order_proof":
        await db.create_second_order_payment(uid,s["fee"],s["utr"],fid); state.pop(uid,None)
        await update.message.reply_text("🔓 2nd order unlock payment received. Assigned Admin verification pending.")
        aid=int(s.get("admin_id") or await db.get_customer_admin(uid) or OWNER_ID)
        if aid:
            try: await context.bot.send_photo(aid,fid,caption=f"🔓 2nd order unlock payment pending from {uid}\n💰 ₹{s['fee']:.0f}\nUTR: {s['utr']}\n🔒 Assigned customer payment.")
            except: pass
    elif action=="priority_proof":
        dbx=await db.connect(); await dbx.execute("INSERT INTO priority_payments(customer_id,amount,utr,proof,created_at) VALUES(?,?,?,?,?)",(uid,s["fee"],s["utr"],fid,db.now())); await dbx.commit(); await dbx.close(); state.pop(uid,None)
        await update.message.reply_text("⭐ Priority payment received. Admin verification pending.")
        aid=int(s.get("admin_id") or await db.get_customer_admin(uid) or OWNER_ID)
        if aid:
            try: await context.bot.send_photo(aid,fid,caption=f"⭐ Priority payment pending from {uid}\n💰 ₹{s['fee']:.0f}\nUTR: {s['utr']}\n🔒 Assigned customer payment.")
            except: pass

async def price_cmd(update,context):
    if not await is_admin(update.effective_user.id) or len(context.args)<2: return
    oid,amount=context.args[0],float(context.args[1]); o=await db.get_order(oid)
    if not o: await update.message.reply_text("❌ Order not found."); return
    enabled=await db.setting("palace_charge_enabled","1")=="1"; charge=float(await db.setting("palace_charge","30")) if enabled else 0
    total=amount+charge+o["priority_fee"]+o["adjustment"]; await db.update_order(oid,swiggy_amount=amount,palace_charge=charge,total=total,status="price_confirmed")
    await update.message.reply_text(f"💰 {oid}\n🍔 Swiggy: ₹{amount:.2f}\n🏰 Palace Charge: ₹{charge:.2f}\n⭐ Priority: ₹{o['priority_fee']:.2f}\n💳 Total: ₹{total:.2f}\n\nCustomer can now pay via bot.",parse_mode="HTML")
    try: await context.bot.send_message(o["customer_id"],f"💰 <b>{oid} Final Price</b>\n🍔 Swiggy: ₹{amount:.2f}\n🏰 Palace: ₹{charge:.2f}\n💳 Total: ₹{total:.2f}",parse_mode="HTML",reply_markup=order_actions(oid))
    except: pass

async def swiggyid_cmd(update,context):
    if not await is_admin(update.effective_user.id) or len(context.args)<2:return
    oid=" ".join(context.args[:-1]); sid=context.args[-1]; await db.update_order(oid,swiggy_order_id=sid); await update.message.reply_text(f"🧾 {oid}: {sid} saved.")

async def set_cmd(update,context,key,label):
    if update.effective_user.id!=OWNER_ID or not context.args: return
    await db.set_setting(key," ".join(context.args)); await update.message.reply_text(f"✅ {label} updated.")

async def setcharge(update,context): await set_cmd(update,context,"palace_charge","Palace charge")
async def setpriority(update,context): await set_cmd(update,context,"priority_fee","Priority fee")
async def setbusiness(update,context): await set_cmd(update,context,"business_open","Business status")
async def setqr(update,context):
    if update.effective_user.id!=OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("🔳 Usage: /setqr <Telegram file_id or image URL>")
        return
    value=" ".join(context.args).strip()
    await db.set_setting("default_qr",value)
    await update.message.reply_text("✅ Default Palace QR saved. Ye QR payment/charge screens par fallback ke roop me use hoga.")

async def feedback_cmd(update,context):
    if not context.args:return
    oid=context.args[0]; o=await db.get_order(oid)
    if not o or o["customer_id"]!=update.effective_user.id or o["status"]!="completed": return
    state[update.effective_user.id]={"action":"feedback_rating","oid":oid}; await update.message.reply_text("⭐ Rating bhejo: 1 se 5 (sirf number).")

async def number_handler(update,context):
    uid=update.effective_user.id; s=state.get(uid)
    if s and s.get("action")=="feedback_rating":
        try:r=max(1,min(5,int(update.message.text)))
        except:return
        await db.update_order(s["oid"],notes="rating:"+str(r)); state[uid]={"action":"feedback_review","oid":s["oid"],"rating":r}; await update.message.reply_text("📝 Short review bhejo, ya /skip.")
    elif s and s.get("action")=="price":
        pass

async def error(update,context):
    log.exception("Unhandled bot error",exc_info=context.error)
    try:
        if update and update.effective_message: await update.effective_message.reply_text("⚠️ Temporary error. Please try again.")
    except: pass

async def health(request): return PlainTextResponse("OK")

async def main():
    if not BOT_TOKEN: raise RuntimeError("BOT_TOKEN is missing")
    await db.init_db()
    await db.ensure_bootstrap_admins(ADMIN_IDS)
    log.info("Database initialized; starting Telegram polling")
    app=Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()\n    global app_global\n    app_global=app
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("admin",admin_cmd))
    app.add_handler(CommandHandler("addadmin",addadmin_cmd))
    app.add_handler(CommandHandler("removeadmin",removeadmin_cmd))
    app.add_handler(CommandHandler("price",price_cmd))
    app.add_handler(CommandHandler("swiggyid",swiggyid_cmd))
    app.add_handler(CommandHandler("setcharge",setcharge))
    app.add_handler(CommandHandler("setpriority",setpriority))
    app.add_handler(CommandHandler("setbusiness",setbusiness))
    app.add_handler(CommandHandler("setqr",setqr))
    app.add_handler(CommandHandler("feedback",feedback_cmd))
    app.add_handler(CommandHandler("skip",lambda u,c: u.message.reply_text("⏭️ Skipped.")))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND,qr_photo_handler))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND,photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_error_handler(error)
    async def post_init(application):
        await application.bot.set_my_commands([
          ("start","🏰 Start Swiggy Palace"),("admin","👑 Admin Panel"),
          ("feedback","⭐ Order Feedback")
        ])
    await app.initialize()
    me=await app.bot.get_me()
    log.info("Telegram bot connected as @%s (%s)", me.username, me.id)
    await post_init(app)
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    log.info("Telegram polling started successfully")
    from uvicorn import Config, Server
    web=Starlette(routes=[Route("/health",health)])
    server=Server(Config(web,host="0.0.0.0",port=PORT,log_level="info"))
    await server.serve()

if __name__=="__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
