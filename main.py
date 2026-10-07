import asyncio, logging, os
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from config import BOT_TOKEN, ADMIN_IDS, OWNER_ID, PORT
import db
from ui import main_menu, admin_menu, order_actions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log=logging.getLogger("swiggy-palace")

# Per-user short-lived input state. Durable business state is kept in SQLite.
state={}

def is_admin(uid): return uid in ADMIN_IDS

async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    u=update.effective_user
    await db.upsert_user(u)
    state.pop(u.id,None)
    await update.message.reply_text(
      f"🏰 <b>Swiggy Palace</b> 👑\n\n🍔 Manual Swiggy Ordering Service\n\n"
      "📍 Send your Swiggy address link\n🛒 Send your cart link\n📸 Send cart screenshot\n"
      "💳 Pay after final price verification\n👨‍💼 Order is manually placed by Palace Admin",
      parse_mode="HTML",reply_markup=main_menu())

async def admin_cmd(update,context):
    if not is_admin(update.effective_user.id): return
    await update.message.reply_text("👑 <b>Swiggy Palace Admin Panel</b>",parse_mode="HTML",reply_markup=admin_menu())

async def callbacks(update:Update,context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); uid=q.from_user.id; data=q.data
    if data=="new_order":
        oid=await db.create_order(uid); state[uid]={"action":"address","oid":oid}
        await q.message.reply_text(f"🛒 <b>{oid}</b> created.\n\n📍 Ab apna <b>Swiggy Address Link</b> bhejo.",parse_mode="HTML")
    elif data=="priority":
        fee=float(await db.setting("priority_fee","49")); state[uid]={"action":"priority_utr","fee":fee}
        await q.message.reply_text(f"⭐ <b>High Priority</b>\n\n💰 Advance: ₹{fee:.0f}\n⏱️ Assignment SLA: {await db.setting('priority_sla_minutes','5')} min\n⚠️ Priority means faster processing, not a guaranteed instant order.\n\n"
          "💳 Payment UTR bhejo aur payment screenshot bhi upload karo.",parse_mode="HTML")
    elif data=="my_orders":
        dbx=await db.connect(); cur=await dbx.execute("SELECT id,status,total FROM orders WHERE customer_id=? ORDER BY created_at DESC LIMIT 10",(uid,)); rows=await cur.fetchall(); await dbx.close()
        text="📦 <b>My Orders</b>\n\n"+("\n".join(f"🆔 {r['id']} • {r['status']} • ₹{r['total']:.0f}" for r in rows) if rows else "No orders yet.")
        await q.message.reply_text(text,parse_mode="HTML")
    elif data=="profile":
        dbx=await db.connect(); cur=await dbx.execute("SELECT * FROM users WHERE id=?",(uid,)); r=await cur.fetchone(); await dbx.close()
        await q.message.reply_text(f"👤 <b>Profile</b>\n⭐ Rating: {(r['rating_sum']/r['rating_count'] if r['rating_count'] else 0):.1f}\n⚠️ Warnings: {r['warnings']}\n📦 Orders: use My Orders",parse_mode="HTML")
    elif data=="help":
        await q.message.reply_text("📖 <b>How it works</b>\n\n1️⃣ Place New Order\n2️⃣ 📍 Address link\n3️⃣ 🛒 Cart link\n4️⃣ 📸 Cart screenshot\n5️⃣ 💰 Palace gives final price\n6️⃣ 💳 Pay + UTR/proof\n7️⃣ ✅ Payment is manually verified\n8️⃣ 👨‍💼 Admin manually places Swiggy order\n9️⃣ 📦 Swiggy Order ID/status shared\n🔟 🏁 Completion + feedback",parse_mode="HTML")
    elif data=="ticket":
        state[uid]={"action":"ticket_subject"}; await q.message.reply_text("🎫 Support ticket ke liye apni problem/message bhejo.")
    elif data.startswith("pay:"):
        oid=data.split(":",1)[1]; o=await db.get_order(oid)
        if not o or o["customer_id"]!=uid: return
        state[uid]={"action":"payment_utr","oid":oid}; await q.message.reply_text(f"💳 <b>{oid}</b>\nTotal payable: ₹{o['total']:.2f}\n\nUTR bhejo, phir payment screenshot upload karo.",parse_mode="HTML")
    elif data.startswith("a_") or data.startswith("approvepay:") or data.startswith("rejectpay:") or data.startswith("placed:") or data.startswith("complete:") or data.startswith("refund:") or data.startswith("reqaddr:") or data.startswith("reqcart:"):
        await admin_callback(q,context,data)
    elif data.startswith("prioapprove:") or data.startswith("prioreject:"):
        await admin_priority_callback(q,data)

async def admin_callback(q,context,data):
    uid=q.from_user.id
    if not is_admin(uid): return
    if data=="a_stats":
        s=await db.stats(); await q.message.reply_text(f"📊 <b>Palace Stats</b>\n👥 Customers: {s['customers']}\n📦 Orders: {s['orders']}\n🏁 Completed: {s['completed']}\n⏳ Active: {s['active']}\n🍔 Swiggy Value: ₹{s['swiggy']:.2f}\n💰 Palace Charges: ₹{s['charges']:.2f}\n↩️ Refunds: ₹{s['refunds']:.2f}",parse_mode="HTML")
    elif data=="a_new":
        dbx=await db.connect(); cur=await dbx.execute("SELECT * FROM orders WHERE status IN ('new','address_received','cart_received','screenshot_received','price_confirmed') ORDER BY priority DESC,created_at ASC LIMIT 20"); rows=await cur.fetchall(); await dbx.close()
        if not rows: await q.message.reply_text("📥 No new orders."); return
        for o in rows:
            await q.message.reply_text(f"📦 <b>{o['id']}</b>\n👤 {o['customer_id']}\n📍 {o['address_link'] or '-'}\n🛒 {o['cart_link'] or '-'}\n💰 Swiggy ₹{o['swiggy_amount']:.2f}\n🏰 Charge ₹{o['palace_charge']:.2f}\n💳 {o['payment_status']}",parse_mode="HTML",reply_markup=order_actions(o["id"]))
    elif data=="a_pay":
        dbx=await db.connect(); cur=await dbx.execute("SELECT o.*,p.utr,p.proof FROM orders o JOIN payments p ON p.order_id=o.id WHERE p.status='pending' ORDER BY o.created_at ASC LIMIT 20"); rows=await cur.fetchall(); await dbx.close()
        if not rows: await q.message.reply_text("💳 No pending payment verification."); return
        for o in rows:
            kb=[[__import__('telegram').InlineKeyboardButton("✅ Approve",callback_data=f"approvepay:{o['id']}"),__import__('telegram').InlineKeyboardButton("❌ Reject",callback_data=f"rejectpay:{o['id']}")]]
            await q.message.reply_text(f"💳 <b>{o['id']}</b>\n💰 ₹{o['total']:.2f}\nUTR: {o['utr']}",parse_mode="HTML",reply_markup=__import__('telegram').InlineKeyboardMarkup(kb))
    elif data=="a_active":
        dbx=await db.connect(); cur=await dbx.execute("SELECT * FROM orders WHERE status NOT IN ('completed','cancelled','refund_completed') ORDER BY priority DESC,updated_at DESC LIMIT 20"); rows=await cur.fetchall(); await dbx.close()
        await q.message.reply_text("📦 Active orders: "+(", ".join(r["id"] for r in rows) if rows else "none"))
    elif data=="a_admins":
        await q.message.reply_text("👨‍💼 Admin management is available through environment OWNER_ID/ADMIN_IDS in this first production build. Database role controls are ready for extension.")
    elif data=="a_charges":
        c=await db.setting("palace_charge","30"); enabled=await db.setting("palace_charge_enabled","1"); pf=await db.setting("priority_fee","49")
        await q.message.reply_text(f"💰 Charge ON: {enabled}\n🏰 Palace charge: ₹{c}\n⭐ Priority fee: ₹{pf}\n\nUse /setcharge amount and /setpriority amount.")
    elif data=="a_qr":
        qr=await db.setting("default_qr",""); await q.message.reply_text("🔳 Default Palace QR: "+(qr or "Not configured")+"\nUse /setqr <Telegram file_id or URL>.")
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
    if not is_admin(q.from_user.id): return
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
        state[uid]={"action":"payment_proof","oid":oid}; await update.message.reply_text("📸 Ab payment screenshot bhejo.")
    elif action=="priority_utr":
        state[uid]={"action":"priority_proof","utr":text,"fee":s["fee"]}; await update.message.reply_text("📸 Priority payment screenshot bhejo.")
    elif action=="swiggyid":
        await db.update_order(oid,swiggy_order_id=text); state.pop(uid,None); await update.message.reply_text(f"🧾 {oid} Swiggy Order ID saved: {text}")

async def photo_handler(update,context):
    uid=update.effective_user.id; s=state.get(uid)
    if not s: return
    fid=update.message.photo[-1].file_id; action=s["action"]; oid=s.get("oid")
    if action=="screenshot":
        await db.update_order(oid,cart_screenshot=fid,status="screenshot_received"); state.pop(uid,None)
        await update.message.reply_text(f"📸 {oid} screenshot received. Palace Admin will verify cart and enter actual Swiggy price.")
        for aid in ADMIN_IDS:
            try: await context.bot.send_message(aid,f"📥 New cart screenshot for {oid} from customer {uid}. Open Admin Panel with /admin.")
            except: pass
    elif action=="payment_proof":
        dbx=await db.connect(); await dbx.execute("UPDATE payments SET proof=?,status='pending',updated_at=? WHERE order_id=?",(fid,db.now(),oid)); await dbx.commit(); await dbx.close(); state.pop(uid,None)
        await update.message.reply_text(f"💳 Payment proof received for {oid}. Manual verification pending.")
        for aid in ADMIN_IDS:
            try: await context.bot.send_photo(aid,fid,caption=f"💳 Payment pending: {oid}\nCustomer: {uid}\nUse /admin → Payments.")
            except: pass
    elif action=="priority_proof":
        dbx=await db.connect(); await dbx.execute("INSERT INTO priority_payments(customer_id,amount,utr,proof,created_at) VALUES(?,?,?,?,?)",(uid,s["fee"],s["utr"],fid,db.now())); await dbx.commit(); await dbx.close(); state.pop(uid,None)
        await update.message.reply_text("⭐ Priority payment received. Admin verification pending.")
        for aid in ADMIN_IDS:
            try: await context.bot.send_photo(aid,fid,caption=f"⭐ Priority payment pending from {uid}. Use /prioritypay.")
            except: pass

async def price_cmd(update,context):
    if not is_admin(update.effective_user.id) or len(context.args)<2: return
    oid,amount=context.args[0],float(context.args[1]); o=await db.get_order(oid)
    if not o: await update.message.reply_text("❌ Order not found."); return
    enabled=await db.setting("palace_charge_enabled","1")=="1"; charge=float(await db.setting("palace_charge","30")) if enabled else 0
    total=amount+charge+o["priority_fee"]+o["adjustment"]; await db.update_order(oid,swiggy_amount=amount,palace_charge=charge,total=total,status="price_confirmed")
    await update.message.reply_text(f"💰 {oid}\n🍔 Swiggy: ₹{amount:.2f}\n🏰 Palace Charge: ₹{charge:.2f}\n⭐ Priority: ₹{o['priority_fee']:.2f}\n💳 Total: ₹{total:.2f}\n\nCustomer can now pay via bot.",parse_mode="HTML")
    try: await context.bot.send_message(o["customer_id"],f"💰 <b>{oid} Final Price</b>\n🍔 Swiggy: ₹{amount:.2f}\n🏰 Palace: ₹{charge:.2f}\n💳 Total: ₹{total:.2f}",parse_mode="HTML",reply_markup=order_actions(oid))
    except: pass

async def swiggyid_cmd(update,context):
    if not is_admin(update.effective_user.id) or len(context.args)<2:return
    oid=" ".join(context.args[:-1]); sid=context.args[-1]; await db.update_order(oid,swiggy_order_id=sid); await update.message.reply_text(f"🧾 {oid}: {sid} saved.")

async def set_cmd(update,context,key,label):
    if update.effective_user.id!=OWNER_ID or not context.args: return
    await db.set_setting(key," ".join(context.args)); await update.message.reply_text(f"✅ {label} updated.")

async def setcharge(update,context): await set_cmd(update,context,"palace_charge","Palace charge")
async def setpriority(update,context): await set_cmd(update,context,"priority_fee","Priority fee")
async def setbusiness(update,context): await set_cmd(update,context,"business_open","Business status")
async def setqr(update,context): await set_cmd(update,context,"default_qr","Default QR")

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
    app=Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("admin",admin_cmd))
    app.add_handler(CommandHandler("price",price_cmd))
    app.add_handler(CommandHandler("swiggyid",swiggyid_cmd))
    app.add_handler(CommandHandler("setcharge",setcharge))
    app.add_handler(CommandHandler("setpriority",setpriority))
    app.add_handler(CommandHandler("setbusiness",setbusiness))
    app.add_handler(CommandHandler("setqr",setqr))
    app.add_handler(CommandHandler("feedback",feedback_cmd))
    app.add_handler(CommandHandler("skip",lambda u,c: u.message.reply_text("⏭️ Skipped.")))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND,photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_error_handler(error)
    async def post_init(application):
        await application.bot.set_my_commands([
          ("start","🏰 Start Swiggy Palace"),("admin","👑 Admin Panel"),
          ("feedback","⭐ Order Feedback")
        ])
    await app.initialize(); await post_init(app); await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    from uvicorn import Config, Server
    web=Starlette(routes=[Route("/health",health)])
    server=Server(Config(web,host="0.0.0.0",port=PORT,log_level="info"))
    await server.serve()

if __name__=="__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
