# Render deploy refresh: keep current production source syntax in sync.
import asyncio, logging, os, json
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse, JSONResponse
from starlette.routing import Route
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from config import BOT_TOKEN, ADMIN_IDS, OWNER_ID, PORT
import db
from ui import main_menu, admin_menu, order_actions, role_menu, mini_admin_menu

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

async def ping_cmd(update:Update, context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚡ Bot is online and replying instantly.")

async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    u=update.effective_user
    await db.upsert_user(u)
    state.pop(u.id,None)
    if await force_join_required(u.id):
        await show_force_join(update.message)
        return
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

async def forcejoin_add_cmd(update,context):
    if update.effective_user.id!=OWNER_ID: return
    if not context.args:
        await update.message.reply_text("Usage: /forcejoin_add @channel"); return
    ch=context.args[0].strip()
    dbx=await db.connect(); cur=await dbx.execute("SELECT value FROM settings WHERE key='force_join_channels'")
    row=await cur.fetchone(); current=[x.strip() for x in ((row["value"] if row else "") or FORCE_JOIN_CHANNEL).split(",") if x.strip()]
    if ch not in current: current.append(ch)
    await dbx.execute("INSERT INTO settings(key,value) VALUES('force_join_channels',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(",".join(current),)); await dbx.commit(); await dbx.close()
    await update.message.reply_text("✅ Force Join channel added: "+ch)

async def forcejoin_remove_cmd(update,context):
    if update.effective_user.id!=OWNER_ID: return
    if not context.args:
        await update.message.reply_text("Usage: /forcejoin_remove @channel"); return
    ch=context.args[0].strip()
    dbx=await db.connect(); cur=await dbx.execute("SELECT value FROM settings WHERE key='force_join_channels'")
    row=await cur.fetchone(); current=[x.strip() for x in ((row["value"] if row else "") or FORCE_JOIN_CHANNEL).split(",") if x.strip()]
    current=[x for x in current if x!=ch]
    await dbx.execute("INSERT INTO settings(key,value) VALUES('force_join_channels',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(",".join(current),)); await dbx.commit(); await dbx.close()
    await update.message.reply_text("🗑️ Force Join channel removed: "+ch)

async def admin_cmd(update,context):
    uid=update.effective_user.id
    if not await is_admin(uid): return
    a=await db.get_admin(uid)
    if a and a["role"]=="mini_admin":
        await update.message.reply_text("🏪 <b>SWIGGY PALACE MINI ADMIN</b>",parse_mode="HTML",reply_markup=mini_admin_menu())
    else:
        await update.message.reply_text("👑 <b>Swiggy Palace Admin Panel</b>",parse_mode="HTML",reply_markup=admin_menu())

async def seller_entry_callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    await q.answer()
    uid=q.from_user.id
    state[uid]={"action":"seller_form","step":0,"data":{}}
    await q.message.edit_text(
        "🏪 <b>SELLER APPLICATION FORM</b>\\n\\n"
        "Swiggy Palace Seller banne ke liye neeche details fill karein.\\n"
        "Har step par aap <b>⏭️ Skip</b> kar sakte hain.\\n\\n"
        "1️⃣ <b>Full Name</b> bhejein:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ Skip",callback_data="seller_skip")],
            [InlineKeyboardButton("⬅️ Back",callback_data="start_roles")]
        ])
    )

async def callbacks(update:Update,context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); uid=q.from_user.id; data=q.data
    if data=="force_join_check":
        if await force_join_required(uid):
            await q.message.reply_text("❌ Pehle @Swiggypalace channel join karein, phir ✅ I Joined dabayein.")
            return
        await mark_force_join_verified(uid)
        await q.message.edit_text("✅ <b>Verification Complete!</b>\n\n🏰 Welcome to Swiggy Palace.\n👇 Ab apna role choose karein.",parse_mode="HTML",reply_markup=role_menu())
        return
    if data.startswith("seller_approve:") or data.startswith("seller_reject:"):
        if uid!=OWNER_ID: return
        sid=int(data.split(":",1)[1]); ok=data.startswith("seller_approve:")
        await db.set_setting("seller_status_"+str(sid),"approved" if ok else "rejected")
        if ok:
            seller_user = await db.get_user(sid)
            seller_name = (
                (json.loads(await db.setting("seller_"+str(sid),"{}") or "{}").get("full_name","") or "").strip()
                or (seller_user["first_name"] if seller_user and seller_user["first_name"] else "")
                or (seller_user["username"] if seller_user and seller_user["username"] else "")
                or f"Telegram {sid}"
            )
            await db.add_admin(sid,"mini_admin",seller_name)
        try: await context.bot.send_message(sid,"🎉 Seller Approved! Mini Admin access enabled." if ok else "❌ Seller application rejected.")
        except Exception: pass
        await q.message.reply_text("✅ Seller approved; Mini Admin enabled." if ok else "❌ Seller rejected."); return
    if data.startswith("feedback:"):
        _,oid,rs=data.split(":",2); rating=int(rs); o=await db.get_order(oid)
        if not o or int(o["customer_id"])!=uid or o["status"]!="completed": return
        state[uid]={"action":"feedback_review","oid":oid,"rating":rating}
        await q.message.reply_text(f"⭐ Rating: {rating}/5\n\n📝 Short review bhejo ya /skip.")
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
        state[uid]={"action":"seller_form","step":0,"data":{}}
        await q.message.edit_text(
          "🏪 <b>SELLER APPLICATION FORM</b>\n\n"
          "Jo details available hain woh fill karein. Jo detail nahi deni ho, <b>Skip</b> karein.\n\n"
          "1️⃣ <b>Full Name</b> bhejein:",
          parse_mode="HTML",
          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip",callback_data="seller_skip")],[InlineKeyboardButton("⬅️ Back",callback_data="start_roles")]]))
        return
    if data=="seller_skip":
        s=state.get(uid)
        if not s or s.get("action")!="seller_form": return
        fields=["full_name","phone","city","experience","upi","business"]
        prompts=["2️⃣ <b>Mobile Number</b> bhejein:","3️⃣ <b>City</b> bhejein:","4️⃣ <b>Experience</b> bhejein:","5️⃣ <b>UPI ID</b> bhejein:","6️⃣ <b>Business / Work Details</b> bhejein:"]
        step=s["step"]
        if step<len(fields): s["data"][fields[step]]="Skipped"; s["step"]=step+1
        if s["step"]>=len(fields): await submit_seller_application(q,context)
        else: await q.message.reply_text(prompts[s["step"]-1],parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip",callback_data="seller_skip")]]))
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
        # Hardened High Priority flow: never expose a generic temporary error.
        try:
            await db.upsert_user(q.from_user)
            user_row = await db.get_user(uid)

            # Legacy SQLite databases may not have the optional priority fields.
            priority_active = 0
            priority_paid = 0
            if user_row:
                try:
                    priority_active = int(user_row["priority"] or 0)
                except Exception:
                    priority_active = 0
                try:
                    priority_paid = int(user_row["priority_paid"] or 0)
                except Exception:
                    priority_paid = 0

            if priority_active == 1 and priority_paid == 1:
                await q.message.reply_text(
                    "⭐ <b>HIGH PRIORITY ACTIVE</b>\n\n"
                    "Aapka High Priority already active hai. Dobara payment ki zarurat nahi hai.",
                    parse_mode="HTML"
                )
                return

            try:
                fee = float(await db.setting("priority_fee", "49") or 49)
            except Exception:
                fee = 49.0

            try:
                sla = str(await db.setting("priority_sla_minutes", "5") or "5").strip()
            except Exception:
                sla = "5"

            aid = await db.get_customer_admin(uid)
            if not aid:
                aid = await db.assign_customer_admin(uid)
            if not aid:
                await q.message.reply_text(
                    "⚠️ <b>High Priority temporarily unavailable</b>\n\n"
                    "Abhi koi active Palace Admin available nahi hai.",
                    parse_mode="HTML"
                )
                return

            try:
                qr, qr_aid = await db.payment_qr_for(uid)
                qr_aid = int(qr_aid or aid)
            except Exception:
                log.exception("Priority QR lookup failed for user=%s", uid)
                qr, qr_aid = "", int(aid)

            if not qr:
                await q.message.reply_text(
                    "⭐ <b>HIGH PRIORITY</b>\n\n"
                    f"💰 Advance: ₹{fee:.0f}\n"
                    f"⏱️ Assignment SLA: {sla} min\n\n"
                    "⚠️ Payment QR abhi configured nahi hai.\n"
                    "Admin Panel → 📷 Payment QR se assigned Admin ka QR set karein.",
                    parse_mode="HTML"
                )
                return

            state[uid] = {
                "action": "priority_utr",
                "fee": fee,
                "admin_id": qr_aid,
                "qr_admin_id": qr_aid,
                "qr_value": qr,
                "qr_source": "assigned_admin"
            }

            msg = (
                f"⭐ <b>HIGH PRIORITY</b>\n\n"
                f"💰 Advance: ₹{fee:.0f}\n"
                f"⏱️ Assignment SLA: {sla} min\n\n"
                "⚠️ Priority means faster processing, not a guaranteed instant order.\n\n"
                "1️⃣ <b>QR par payment karo</b>\n"
                "2️⃣ Payment ka <b>UTR number</b> bhejo\n"
                "3️⃣ Uske baad <b>payment screenshot</b> upload karo.\n\n"
                "🔒 Screenshot sirf aapke assigned Palace Admin ko jayega."
            )
            try:
                await q.message.reply_photo(qr, caption=msg, parse_mode="HTML")
            except Exception:
                await q.message.reply_text(msg + f"\n\n🔳 QR: {qr}", parse_mode="HTML")
        except Exception as exc:
            log.exception("High Priority callback failed for user=%s: %s", uid, exc)
            state.pop(uid, None)
            try:
                await q.message.reply_text(
                    "⚠️ High Priority abhi open nahi ho paayi. Please dobara ⭐ High Priority dabayein."
                )
            except Exception:
                pass
    elif data=="my_orders":
        dbx=await db.connect(); cur=await dbx.execute(
            "SELECT id,status,total,swiggy_order_id,updated_at FROM orders WHERE customer_id=? ORDER BY created_at DESC LIMIT 10",
            (uid,)
        ); rows=await cur.fetchall(); await dbx.close()
        if not rows:
            await q.message.reply_text("📦 <b>My Orders</b>\n\nNo orders yet.",parse_mode="HTML")
            return
        lines=["📦 <b>MY ORDERS</b>",""]
        buttons=[]
        for r in rows:
            total=float(r["total"] or 0)
            swid=r["swiggy_order_id"] or "-"
            lines.append(f"🆔 <code>{r['id']}</code> • <b>{r['status']}</b> • ₹{total:.0f}\n🧾 Swiggy ID: {swid}")
            buttons.append([InlineKeyboardButton(f"🔄 Check Status — {r['id']}",callback_data=f"orderstatus:{r['id']}")])
        buttons.append([InlineKeyboardButton("🛒 Place New Order",callback_data="new_order")])
        await q.message.reply_text("\n".join(lines),parse_mode="HTML",reply_markup=InlineKeyboardMarkup(buttons))
    elif data.startswith("orderstatus:"):
        oid=data.split(":",1)[1].strip()
        o=await db.get_order(oid)
        if not o or int(o["customer_id"])!=uid:
            await q.message.reply_text("❌ Order not found.")
            return
        def _money(v):
            try: return f"{float(v or 0):.2f}"
            except (TypeError,ValueError): return "0.00"
        status=str(o["status"] or "-")
        swiggy_id=str(o["swiggy_order_id"] or "-")
        total=_money(o["total"])
        swiggy_amount=_money(o["swiggy_amount"])
        palace_charge=_money(o["palace_charge"])
        priority_fee=_money(o["priority_fee"])
        msg=(f"📦 <b>ORDER STATUS</b>\n\n"
             f"🆔 Order: <code>{o['id']}</code>\n"
             f"📌 Status: <b>{status}</b>\n"
             f"🧾 Swiggy Order ID: <code>{swiggy_id}</code>\n\n"
             f"🍔 Swiggy Amount: ₹{swiggy_amount}\n"
             f"🏰 Palace Charge: ₹{palace_charge}\n"
             f"⭐ Priority Fee: ₹{priority_fee}\n"
             f"💳 Total: ₹{total}")
        kb=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh Status",callback_data=f"orderstatus:{oid}")],
            [InlineKeyboardButton("📦 My Orders",callback_data="my_orders")],
            [InlineKeyboardButton("🛒 Place New Order",callback_data="new_order")]
        ])
        await q.message.reply_text(msg,parse_mode="HTML",reply_markup=kb)
        return
    elif data=="profile":
        dbx=await db.connect(); cur=await dbx.execute("SELECT * FROM users WHERE id=?",(uid,)); r=await cur.fetchone(); await dbx.close()
        await q.message.reply_text(f"👤 <b>Profile</b>\n⭐ Rating: {(r['rating_sum']/r['rating_count'] if r['rating_count'] else 0):.1f}\n⚠️ Warnings: {r['warnings']}\n📦 Orders: use My Orders",parse_mode="HTML")
    elif data=="help":
        await q.message.reply_text("📖 <b>How it works</b>\n\n1️⃣ Place New Order\n2️⃣ 📍 Address link\n3️⃣ 🛒 Cart link\n4️⃣ 📸 Cart screenshot\n5️⃣ 💰 Palace gives final price\n6️⃣ 💳 Pay + UTR/proof\n7️⃣ ✅ Payment is manually verified\n8️⃣ 👨‍💼 Admin manually places Swiggy order\n9️⃣ 📦 Swiggy Order ID/status shared\n🔟 🏁 Completion + feedback",parse_mode="HTML")
    elif data=="help_support" or data=="ticket":
        state[uid]={"action":"ticket_subject"}
        await q.message.reply_text("🆘 <b>Help & Support</b>\n\nApni query/problem ek message me likho.\nAapki query Ticket ID aur unique ID ke saath Owner ko milegi.",parse_mode="HTML")
    elif data.startswith("userview:"):
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
    elif data.startswith("setid:"):
        if not await is_admin(uid): return
        oid=data.split(":",1)[1]; o=await db.get_order(oid)
        if not o or (uid!=OWNER_ID and o["assigned_admin"] and int(o["assigned_admin"])!=uid): return
        state[uid]={"action":"swiggyid","oid":oid}
        await q.message.reply_text(f"🧾 <b>{oid}</b>\\n\\nSwiggy Order ID bhejo:",parse_mode="HTML")
    elif data.startswith("setprice:"):
        if not await is_admin(uid): return
        oid=data.split(":",1)[1]; o=await db.get_order(oid)
        if not o or (uid!=OWNER_ID and o["assigned_admin"] and int(o["assigned_admin"])!=uid): return
        state[uid]={"action":"final_price","oid":oid}
        await q.message.reply_text(f"💰 <b>{oid}</b>\\n\\nFinal Swiggy price ₹ me bhejo:",parse_mode="HTML")
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
        assigned_admin = int(o["assigned_admin"] or 0)
        state[uid]={"action":"payment_utr","oid":oid,"qr_admin_id":assigned_admin,"qr_value":qr,"qr_source":"assigned_admin"}
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
    elif data.startswith("userview:") or data.startswith("a_") or data.startswith("approvepay:") or data.startswith("rejectpay:") or data.startswith("placed:") or data.startswith("complete:") or data.startswith("refund:") or data.startswith("reqaddr:") or data.startswith("reqcart:"):
        await admin_callback(q,context,data)
    elif data.startswith("prioapprove:") or data.startswith("prioreject:"):
        await admin_priority_callback(q,data)

async def submit_seller_application(target,context):
    uid=target.from_user.id if hasattr(target,"from_user") else target.effective_user.id
    s=state.get(uid,{})
    data=s.get("data",{})
    await db.set_setting("seller_"+str(uid),json.dumps(data))
    pid=await db.assign_public_id(uid,"seller")
    msg=(f"🏪 <b>NEW SELLER APPLICATION</b>\n\n🪪 Seller ID: <code>{pid}</code>\n🆔 Telegram ID: <code>{uid}</code>\n"
         f"👤 Name: {data.get('full_name','-')}\n📱 Phone: {data.get('phone','-')}\n📍 City: {data.get('city','-')}\n"
         f"💼 Experience: {data.get('experience','-')}\n💳 UPI: {data.get('upi','-')}\n🏪 Business: {data.get('business','-')}")
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve Seller",callback_data=f"seller_approve:{uid}"),InlineKeyboardButton("❌ Reject",callback_data=f"seller_reject:{uid}")]])
    try: await context.bot.send_message(OWNER_ID,msg,parse_mode="HTML",reply_markup=kb)
    except Exception as e: log.warning("Seller notification failed: %s",e)
    state.pop(uid,None)
    msg_obj=target.message if hasattr(target,"message") else target.effective_message
    await msg_obj.reply_text("✅ <b>Application submitted!</b>\n\n👑 Super Admin approval ke baad Mini Admin access milega.",parse_mode="HTML",reply_markup=role_menu())

async def broadcast_callback(q,context):
    uid=q.from_user.id
    if uid!=OWNER_ID:
        await q.message.reply_text("🔒 Sirf Super Admin broadcast bhej sakta hai.")
        return
    state[uid]={"action":"broadcast"}
    await q.message.reply_text("📢 <b>BROADCAST</b>\n\nApna message bhejo. Ye sab registered users ko send hoga.\n\n❌ Cancel: /cancel",parse_mode="HTML")

async def skip_cmd(update,context):
    uid=update.effective_user.id
    s=state.get(uid)
    if s and s.get("action")=="feedback_review":
        oid=s.get("oid"); o=await db.get_order(oid)
        if o and int(o["customer_id"])==uid and o["status"]=="completed":
            rating=int(s.get("rating",5)); dbx=await db.connect()
            await dbx.execute("UPDATE users SET rating_sum=rating_sum+?,rating_count=rating_count+1 WHERE id=?",(rating,uid))
            await dbx.execute("UPDATE orders SET notes=COALESCE(notes,'') || ?,updated_at=? WHERE id=?",("\nfeedback:"+str(rating)+":",db.now(),oid))
            await dbx.commit(); await dbx.close()
            state.pop(uid,None)
            await update.message.reply_text("🙏 Rating save ho gaya.")
            return
    state.pop(uid,None)
    await update.message.reply_text("⏭️ Skipped.")

async def cancel_cmd(update,context):
    state.pop(update.effective_user.id,None)
    await update.message.reply_text("❌ Cancelled.")

async def admin_callback(q,context,data):
    uid=q.from_user.id
    if not await is_admin(uid): return
    if data.startswith("seller_approve:") or data.startswith("seller_reject:"):
        if uid!=OWNER_ID: return
        sid=int(data.split(":")[1]); ok=data.startswith("seller_approve:")
        await db.set_setting("seller_status_"+str(sid),"approved" if ok else "rejected")
        if ok: await db.add_admin(sid,"mini_admin","Seller")
        try: await context.bot.send_message(sid,"🎉 <b>Seller Approved!</b>\n🏰 Mini Admin access enabled." if ok else "❌ Seller application rejected.",parse_mode="HTML")
        except: pass
        await q.message.reply_text("✅ Seller approved; Mini Admin enabled." if ok else "❌ Seller rejected.")
        return
    if data=="a_broadcast":
        await broadcast_callback(q,context)
    elif data=="a_stats":
        s=await db.stats(); await q.message.reply_text(f"📊 <b>Palace Stats</b>\n👥 Customers: {s['customers']}\n📦 Orders: {s['orders']}\n🏁 Completed: {s['completed']}\n⏳ Active: {s['active']}\n🍔 Swiggy Value: ₹{s['swiggy']:.2f}\n💰 Palace Charges: ₹{s['charges']:.2f}\n↩️ Refunds: ₹{s['refunds']:.2f}",parse_mode="HTML")
    elif data=="a_second":
        dbx=await db.connect(); cur=await dbx.execute("SELECT customer_id,paid_amount,utr FROM second_order_unlocks WHERE status='pending' ORDER BY created_at ASC LIMIT 20"); rows=await cur.fetchall(); await dbx.close()
        if not rows:
            await q.message.reply_text("🔓 No pending 2nd-order unlock payments."); return
        for x in rows:
            kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Verify",callback_data=f"secondapprove:{x['customer_id']}"),InlineKeyboardButton("❌ Reject",callback_data=f"secondreject:{x['customer_id']}")]])
            await q.message.reply_text(f"🔓 <b>2nd Order Unlock</b>\n👤 Customer: <code>{x['customer_id']}</code>\n💰 ₹{x['paid_amount']:.2f}\nUTR: {x['utr']}",parse_mode="HTML",reply_markup=kb)
    elif data.startswith("secondapprove:") or data.startswith("secondreject:"):
        if uid!=OWNER_ID: return
        cid=int(data.split(":",1)[1]); ok=data.startswith("secondapprove:")
        await db.verify_second_order_unlock(cid,uid,ok)
        try: await context.bot.send_message(cid,"✅ 2nd order unlock verified. Ab New Order open karke next order bana sakte ho." if ok else "❌ 2nd order unlock payment rejected.",parse_mode="HTML")
        except Exception: pass
        await q.message.reply_text("✅ Unlock verified." if ok else "❌ Unlock rejected.")
    elif data=="a_back":
        await q.message.reply_text("👑 <b>Admin Panel</b>",parse_mode="HTML",reply_markup=admin_menu())
    elif data=="a_receive":
        if not await is_admin(uid): return
        dbx=await db.connect()
        cur=await dbx.execute("SELECT o.*,p.utr,p.proof FROM orders o JOIN payments p ON p.order_id=o.id WHERE p.status='pending' AND (o.assigned_admin=? OR ?=1) ORDER BY o.created_at ASC LIMIT 20",(uid,1 if uid==OWNER_ID else 0))
        rows=await cur.fetchall(); await dbx.close()
        if not rows:
            await q.message.reply_text("📥 <b>PAYMENT RECEIVE</b>\\n\\nNo pending payment received.",parse_mode="HTML"); return
        for o in rows:
            if uid!=OWNER_ID and o["assigned_admin"] and int(o["assigned_admin"])!=uid: continue
            kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Receive / Approve",callback_data=f"approvepay:{o['id']}"),InlineKeyboardButton("❌ Reject",callback_data=f"rejectpay:{o['id']}")]])
            caption=f"📥 <b>PAYMENT RECEIVE</b>\\n\\n🆔 {o['id']}\\n💰 ₹{o['total']:.2f}\\n🧾 UTR: <code>{o['utr']}</code>\\n👤 Customer: <code>{o['customer_id']}</code>"
            try:
                if o["proof"]:
                    await q.message.reply_photo(o["proof"],caption=caption,parse_mode="HTML",reply_markup=kb)
                else:
                    await q.message.reply_text(caption+"\\n\\n⚠️ Screenshot not received.",parse_mode="HTML",reply_markup=kb)
            except Exception:
                await q.message.reply_text(caption,parse_mode="HTML",reply_markup=kb)
    elif data=="a_search":
        if not await is_admin(uid): return
        state[uid]={"action":"admin_search"}
        await q.message.reply_text("🔎 <b>SEARCH ID</b>\\n\\nOrder ID, Customer Telegram ID ya Public ID bhejo.",parse_mode="HTML")
    elif data=="a_forcejoin":
        if uid!=OWNER_ID:
            await q.message.reply_text("🔒 Sirf Super Admin Force Join manage kar sakta hai."); return
        dbx=await db.connect()
        cur=await dbx.execute("SELECT value FROM settings WHERE key='force_join_channels'")
        row=await cur.fetchone(); await dbx.close()
        channels=[x.strip() for x in ((row["value"] if row else "") or FORCE_JOIN_CHANNEL).split(",") if x.strip()]
        await q.message.reply_text("📢 <b>FORCE JOIN</b>\\n\\nCurrent channels:\\n"+("\\n".join("• "+x for x in channels) if channels else "• None")+
            "\\n\\nUse /forcejoin_add @channel to add.\\nUse /forcejoin_remove @channel to remove.",parse_mode="HTML")
    elif data=="a_support":
        if not await is_admin(uid): return
        dbx=await db.connect()
        cur=await dbx.execute("SELECT id,customer_id,subject,created_at FROM tickets ORDER BY created_at DESC LIMIT 20")
        rows=await cur.fetchall(); await dbx.close()
        if not rows:
            await q.message.reply_text("🎫 <b>HELP & SUPPORT</b>\\n\\nNo tickets.",parse_mode="HTML"); return
        await q.message.reply_text("🎫 <b>RECENT SUPPORT TICKETS</b>\\n\\n"+("\\n".join(f"#{x['id']} • {x['customer_id']} • {x['subject']}" for x in rows)),parse_mode="HTML")
    elif data=="m_profile":
        a=await db.get_admin(uid)
        await q.message.reply_text(f"👤 <b>My Profile</b>\\n\\n🆔 Telegram ID: <code>{uid}</code>\\n👤 Name: {(a['display_name'] if a else q.from_user.first_name) or '-'}\\n🔑 Role: {(a['role'] if a else 'admin')}",parse_mode="HTML",reply_markup=mini_admin_menu())
    elif data=="m_stats":
        dbx=await db.connect()
        cur=await dbx.execute("SELECT COUNT(*) n FROM orders WHERE assigned_admin=?",(uid,)); n=(await cur.fetchone())["n"]
        cur=await dbx.execute("SELECT COUNT(*) n FROM orders WHERE assigned_admin=? AND status NOT IN ('completed','cancelled','refund_completed')",(uid,)); active=(await cur.fetchone())["n"]
        await dbx.close()
        await q.message.reply_text(f"📊 <b>My Stats</b>\\n\\n📦 Total Assigned: {n}\\n⏳ Active: {active}",parse_mode="HTML",reply_markup=mini_admin_menu())
    elif data=="m_qr":
        a=await db.get_admin(uid)
        if a and a["qr_enabled"] and a["qr_value"]:
            await q.message.reply_photo(a["qr_value"],caption="📷 Your assigned payment QR",reply_markup=mini_admin_menu())
        else:
            await q.message.reply_text("📷 Your Admin QR is not configured. Super Admin se QR set karwayein.",reply_markup=mini_admin_menu())
    elif data=="m_support":
        state[uid]={"action":"ticket_subject"}
        await q.message.reply_text("💬 Support query likho. Ye support ticket ke roop me save hogi.",parse_mode="HTML")
    elif data=="m_new" or data=="m_active" or data=="m_pay" or data=="m_customers":
        if not await is_admin(uid): return
        if data=="m_pay":
            dbx=await db.connect(); cur=await dbx.execute("SELECT o.*,p.utr,p.proof FROM orders o JOIN payments p ON p.order_id=o.id WHERE p.status='pending' AND o.assigned_admin=? ORDER BY o.created_at ASC LIMIT 20",(uid,)); rows=await cur.fetchall(); await dbx.close()
            if not rows: await q.message.reply_text("💳 No pending payments.",reply_markup=mini_admin_menu()); return
            for o in rows:
                kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Receive / Approve",callback_data=f"approvepay:{o['id']}"),InlineKeyboardButton("❌ Reject",callback_data=f"rejectpay:{o['id']}")]])
                cap=f"💳 <b>{o['id']}</b>\\n💰 ₹{o['total']:.2f}\\n🧾 UTR: <code>{o['utr']}</code>"
                if o["proof"]:
                    try: await q.message.reply_photo(o["proof"],caption=cap,parse_mode="HTML",reply_markup=kb)
                    except Exception: await q.message.reply_text(cap,parse_mode="HTML",reply_markup=kb)
                else: await q.message.reply_text(cap+"\\n⚠️ Proof missing.",parse_mode="HTML",reply_markup=kb)
        elif data=="m_customers":
            dbx=await db.connect(); cur=await dbx.execute("SELECT DISTINCT customer_id FROM orders WHERE assigned_admin=? ORDER BY created_at DESC LIMIT 30",(uid,)); rows=await cur.fetchall(); await dbx.close()
            await q.message.reply_text("👥 <b>MY CUSTOMERS</b>\\n\\n"+("\\n".join("• <code>"+str(x["customer_id"])+"</code>" for x in rows) if rows else "No assigned customers."),parse_mode="HTML",reply_markup=mini_admin_menu())
        else:
            status_clause="status NOT IN ('completed','cancelled','refund_completed')" if data=="m_active" else "status IN ('new','address_received','cart_received','screenshot_received','price_confirmed')"
            dbx=await db.connect(); cur=await dbx.execute(f"SELECT id,status,total FROM orders WHERE assigned_admin=? AND {status_clause} ORDER BY priority DESC,created_at ASC LIMIT 20",(uid,)); rows=await cur.fetchall(); await dbx.close()
            if not rows: await q.message.reply_text("📦 No matching orders.",reply_markup=mini_admin_menu()); return
            kb=[[InlineKeyboardButton(f"🆔 {x['id']} • {x['status']}",callback_data=f"orderview:{x['id']}")] for x in rows]
            await q.message.reply_text("📥 <b>MY ORDERS</b>" if data=="m_new" else "📦 <b>ACTIVE ORDERS</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))
    elif data=="a_new":
        dbx=await db.connect(); cur=await dbx.execute("SELECT id FROM orders WHERE status IN ('new','address_received','cart_received','screenshot_received','price_confirmed') ORDER BY priority DESC,created_at ASC LIMIT 20"); rows=await cur.fetchall(); await dbx.close()
        if not rows:
            await q.message.reply_text("📥 <b>NEW ORDERS</b>\n\nNo new orders.",parse_mode="HTML"); return
        kb=[[InlineKeyboardButton(f"🆔 {o['id']}",callback_data=f"orderview:{o['id']}")] for o in rows]
        kb += [[InlineKeyboardButton("🔄 Refresh",callback_data="a_new"),InlineKeyboardButton("⬅️ Back",callback_data="a_back")]]
        await q.message.reply_text("📥 <b>NEW ORDERS</b>\n\nTap an Order ID to view details.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("orderview:"):
        oid = data.split(":", 1)[1].strip()
        if not oid:
            await q.message.reply_text("❌ Invalid Order ID.")
            return

        try:
            o = await db.get_order(oid)
            if not o:
                await q.message.reply_text("❌ Order not found.")
                return

            def val(key, default=""):
                try:
                    value = o[key]
                except (KeyError, IndexError, TypeError):
                    value = default
                return default if value is None else value

            try:
                assigned_id = int(val("assigned_admin", 0) or 0)
            except (TypeError, ValueError):
                assigned_id = 0

            if uid != OWNER_ID and assigned_id and assigned_id != uid:
                await q.message.reply_text("🔒 Ye order kisi aur Admin ko assigned hai.")
                return

            try:
                customer_id = int(val("customer_id", 0) or 0)
            except (TypeError, ValueError):
                customer_id = 0

            customer = await db.get_user(customer_id) if customer_id else None
            assigned = await db.get_admin(assigned_id) if assigned_id else None

            # Resolve the latest Telegram profile too, so admin order details
            # still show the customer's name when the local DB has old/missing data.
            telegram_customer = None
            if customer_id:
                try:
                    telegram_customer = await context.bot.get_chat(customer_id)
                except Exception:
                    telegram_customer = None

            from html import escape

            def clean(value, fallback="-"):
                value = fallback if value in (None, "") else value
                return escape(str(value))

            def money(value):
                try:
                    return f"{float(value or 0):.2f}"
                except (TypeError, ValueError):
                    return "0.00"

            customer_name = clean(
                (customer["first_name"] if customer else "") or
                (customer["username"] if customer else "") or
                (getattr(telegram_customer, "first_name", "") if telegram_customer else "") or
                (getattr(telegram_customer, "username", "") if telegram_customer else "") or
                customer_id or "Customer"
            )
            customer_public_id = clean(
                customer["public_id"] if customer and customer["public_id"] else
                f"TG-{customer_id}" if customer_id else "-"
            )
            # Always show a real seller/admin identity when possible.
            # Older admin rows may have an empty/default display name, so fall
            # back to the linked Telegram user's current profile.
            assigned_user = await db.get_user(assigned_id) if assigned_id else None
            assigned_name = clean(
                (assigned["display_name"] if assigned and assigned["display_name"] else "") or
                (assigned_user["first_name"] if assigned_user and assigned_user["first_name"] else "") or
                (assigned_user["username"] if assigned_user and assigned_user["username"] else "") or
                (f"Telegram {assigned_id}" if assigned_id else "Unassigned")
            )

            msg = (
                "📦 <b>ORDER DETAILS</b>\\n\\n"
                f"🆔 Order ID: <code>{clean(val('id', oid))}</code>\\n"
                f"👤 Customer: <b>{customer_name}</b> (<code>{customer_public_id}</code>)\\n"
                f"🆔 Telegram ID: <code>{customer_id or '-'}</code>\\n"
                f"👨‍💼 Assigned Admin/Seller: <b>{assigned_name}</b>\\n"
                f"📌 Status: <b>{clean(val('status'))}</b>\\n"
                f"🍔 Swiggy Amount: ₹{money(val('swiggy_amount', 0))}\\n"
                f"🏰 Palace Charge: ₹{money(val('palace_charge', 0))}\\n"
                f"⭐ Priority Fee: ₹{money(val('priority_fee', 0))}\\n"
                f"💳 Total: ₹{money(val('total', 0))}\\n"
                f"💰 Payment: <b>{clean(val('payment_status'))}</b>\\n"
                f"🧾 Swiggy Order ID: {clean(val('swiggy_order_id'))}\\n\\n"
                f"📍 Address: {clean(val('address_link'))}\\n"
                f"🛒 Cart: {clean(val('cart_link'))}"
            )

            buttons = [
                [InlineKeyboardButton("👤 Open Customer", callback_data=f"userview:{customer_id}")] if customer_id else [],
                [InlineKeyboardButton("💳 Payment", callback_data=f"pay:{oid}"),
                 InlineKeyboardButton("📍 Request Address", callback_data=f"reqaddr:{oid}")],
                [InlineKeyboardButton("🛒 Request Cart", callback_data=f"reqcart:{oid}")],
                [InlineKeyboardButton("🧾 Set Swiggy Order ID", callback_data=f"setid:{oid}")],
                [InlineKeyboardButton("💰 Set Final Price", callback_data=f"setprice:{oid}")],
                [InlineKeyboardButton("✅ Mark Placed", callback_data=f"placed:{oid}"),
                 InlineKeyboardButton("🏁 Complete", callback_data=f"complete:{oid}")],
                [InlineKeyboardButton("↩️ Refund", callback_data=f"refund:{oid}")],
                [InlineKeyboardButton("⬅️ Back", callback_data="a_new")]
            ]
            buttons = [row for row in buttons if row]
            await q.message.reply_text(
                msg,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        except Exception:
            log.exception("Order details failed for order=%s user=%s", oid, uid)
            try:
                await q.message.reply_text(
                    "⚠️ Order details load nahi ho paayi. Please Refresh karke dobara try karein."
                )
            except Exception:
                pass
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
        await q.message.reply_text("⚙️ <b>Settings</b>\n\n💰 /setcharge 30\n⭐ /setpriority 49\n🏪 /setbusiness on|off\n\n📷 Payment QR ab <b>Admin Panel → 📷 Payment QR → Upload Default QR Photo</b> se set karein.",parse_mode="HTML")
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
        try:
            kb=InlineKeyboardMarkup([[InlineKeyboardButton("⭐1",callback_data=f"feedback:{oid}:1"),InlineKeyboardButton("⭐2",callback_data=f"feedback:{oid}:2"),InlineKeyboardButton("⭐3",callback_data=f"feedback:{oid}:3"),InlineKeyboardButton("⭐4",callback_data=f"feedback:{oid}:4"),InlineKeyboardButton("⭐5",callback_data=f"feedback:{oid}:5")]])
            await context.bot.send_message(o["customer_id"],f"🏁 <b>{oid}</b> completed!\n\n⭐ Rate your experience:",parse_mode="HTML",reply_markup=kb)
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
    verifier = q.from_user.id
    if not await is_admin(verifier):
        return

    o = await db.get_order(oid)
    if not o:
        await q.message.reply_text("❌ Order not found.")
        return

    assigned = o["assigned_admin"]
    try:
        assigned = int(assigned) if assigned not in (None, "", "0") else None
    except (TypeError, ValueError):
        assigned = None

    # Assigned Admin OR Super Admin only.
    if verifier != OWNER_ID and assigned != verifier:
        await q.message.reply_text(
            "🔒 Payment approval restricted. Sirf assigned Admin ya Super Admin approve/reject kar sakta hai."
        )
        return

    payment = await db.payment_record(oid)
    if not payment:
        await q.message.reply_text("❌ Payment record not found.")
        return

    if str(payment["status"]) != "pending":
        await q.message.reply_text(
            f"ℹ️ This payment is already {payment['status']}."
        )
        return

    await db.approve_payment_record(oid, verifier, ok)
    await db.update_order(
        oid,
        payment_status="verified" if ok else "rejected",
        status="ready_to_place" if ok else "price_confirmed"
    )
    await db.audit(
        verifier,
        "payment_approved" if ok else "payment_rejected",
        oid,
        f"assigned_admin={assigned}; qr_admin_id={payment['qr_admin_id']}; qr_source={payment['qr_source']}"
    )

    customer = await db.get_user(int(o["customer_id"]))
    assigned_admin_row = await db.get_admin(assigned) if assigned else None
    customer_name = ((customer["first_name"] if customer else "") or "Customer").strip()
    customer_uid = (customer["public_id"] if customer else None) or f"TG-{o['customer_id']}"
    seller_name = ((assigned_admin_row["display_name"] if assigned_admin_row else "") or "Assigned Seller").strip()
    seller_uid = f"SP-SELL-{assigned:04d}" if assigned else "SP-SELL-UNASSIGNED"

    try:
        await q.get_bot().send_message(
            o["customer_id"],
            (
                f"✅ <b>Payment Approved</b>\n"
                f"🆔 Order: <code>{oid}</code>\n"
                f"👤 Customer: <b>{customer_name}</b> (<code>{customer_uid}</code>)\n"
                f"🏪 Seller/Admin: <b>{seller_name}</b> (<code>{seller_uid}</code>)\n"
                "Payment manually verified. Your order is ready for processing."
                if ok else
                f"❌ <b>Payment Rejected</b>\n"
                f"🆔 Order: <code>{oid}</code>\n"
                f"👤 Customer: <b>{customer_name}</b> (<code>{customer_uid}</code>)\n"
                f"🏪 Seller/Admin: <b>{seller_name}</b> (<code>{seller_uid}</code>)\n"
                "Payment could not be verified. Please contact your assigned Admin."
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass

    who = "Super Admin" if verifier == OWNER_ID else "Assigned Admin"
    await q.message.reply_text(
        ("✅ Payment approved." if ok else "❌ Payment rejected.")
        + f" {oid}\n👤 Verified by: {who}"
    )

async def admin_priority_callback(q,data):
    if not await is_admin(q.from_user.id):
        await q.answer("Not authorized", show_alert=True)
        return
    try:
        uid=int(data.split(":",1)[1])
    except (ValueError,IndexError):
        await q.answer("Invalid customer", show_alert=True)
        return

    ok=data.startswith("prioapprove:")
    dbx=await db.connect()
    try:
        cur=await dbx.execute(
            "SELECT amount,utr FROM priority_payments WHERE customer_id=? AND status='pending' "
            "ORDER BY created_at DESC LIMIT 1",
            (uid,)
        )
        pending=await cur.fetchone()
        if not pending:
            await q.answer("No pending priority payment", show_alert=True)
            return

        await dbx.execute(
            "UPDATE priority_payments SET status=?,verified_by=? "
            "WHERE customer_id=? AND status='pending'",
            ("verified" if ok else "rejected",q.from_user.id,uid)
        )
        await dbx.execute(
            "UPDATE users SET priority=?,priority_paid=? WHERE id=?",
            (1 if ok else 0,1 if ok else 0,uid)
        )
        await dbx.commit()
    finally:
        await dbx.close()

    try:
        await q.answer("Priority activated" if ok else "Priority rejected")
    except Exception:
        pass

    try:
        await q.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    customer=await db.get_user(uid)
    cname=(customer["first_name"] if customer else "") or (customer["username"] if customer else "") or f"Telegram {uid}"
    try:
        await context.bot.send_message(
            uid,
            (
                "⭐ <b>HIGH PRIORITY ACTIVE</b>\n\n"
                "Aapka High Priority payment verify ho gaya hai.\n"
                "Aapka order faster processing queue me hai."
                if ok else
                "❌ <b>HIGH PRIORITY PAYMENT REJECTED</b>\n\n"
                "Payment verify nahi hua. Please assigned Admin se contact karein."
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await q.message.reply_text(
        f"⭐ Priority {'activated' if ok else 'rejected'} for <b>{cname}</b> "
        f"(<code>{uid}</code>).",
        parse_mode="HTML"
    )

async def text_handler(update:Update,context:ContextTypes.DEFAULT_TYPE):
    u=update.effective_user; uid=u.id; await db.upsert_user(u); s=state.get(uid); text=update.message.text
    if not s: return
    action=s["action"]; oid=s.get("oid")
    if action=="admin_search":
        if not await is_admin(uid): return
        state.pop(uid,None)
        target=text.strip()
        o=await db.get_order(target)
        if o:
            await update.message.reply_text(f"🔎 Order found: <code>{o['id']}</code>\\nStatus: {o['status']}\\nCustomer: <code>{o['customer_id']}</code>\\nTotal: ₹{o['total']:.2f}",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 Open Order",callback_data=f"orderview:{o['id']}")]])); return
        try:
            cid=int(target)
            u2=await db.get_user(cid)
            if u2: await update.message.reply_text(f"👤 Customer found\\nID: <code>{cid}</code>\\nPublic ID: <code>{u2['public_id'] or '-'}</code>",parse_mode="HTML"); return
        except Exception: pass
        await update.message.reply_text("❌ Order/Customer not found.")
        return
    if action=="final_price":
        try: amount=float(text.replace(",","").replace("₹","").strip())
        except Exception:
            await update.message.reply_text("❌ Valid amount bhejo, e.g. 349.50"); return
        oid=s.get("oid"); o=await db.get_order(oid)
        if not o or not await is_admin(uid): return
        if uid!=OWNER_ID and o["assigned_admin"] and int(o["assigned_admin"])!=uid: return
        charge=float(await db.setting("palace_charge","30")) if await db.setting("palace_charge_enabled","1")=="1" else 0
        priority=float(o["priority_fee"] or 0)
        total=amount+charge+priority
        await db.update_order(oid,swiggy_amount=amount,palace_charge=charge,total=total,status="price_confirmed")
        state.pop(uid,None)
        await update.message.reply_text(f"✅ Final price saved.\\n🆔 {oid}\\n🍔 Swiggy: ₹{amount:.2f}\\n🏰 Palace: ₹{charge:.2f}\\n⭐ Priority: ₹{priority:.2f}\\n💳 Total: ₹{total:.2f}",parse_mode="HTML")
        try: await context.bot.send_message(o["customer_id"],f"💰 <b>{oid} FINAL PRICE</b>\\n\\n💳 Total payable: <b>₹{total:.2f}</b>\\n👇 Payment button order details se available hai.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💳 Pay Now",callback_data=f"pay:{oid}")]]))
        except Exception: pass
        return
    if action=="seller_form":
        fields=["full_name","phone","city","experience","upi","business"]
        prompts=["2️⃣ <b>Mobile Number</b> bhejein:","3️⃣ <b>City</b> bhejein:","4️⃣ <b>Experience</b> bhejein:","5️⃣ <b>UPI ID</b> bhejein:","6️⃣ <b>Business / Work Details</b> bhejein:"]
        step=s.get("step",0)
        s["data"][fields[step]]=text.strip(); s["step"]=step+1
        if s["step"]>=len(fields): await submit_seller_application(update,context)
        else: await update.message.reply_text(prompts[s["step"]-1],parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip",callback_data="seller_skip")]]))
        return
    if action=="feedback_rating":
        try: rating=max(1,min(5,int(text)))
        except Exception:
            await update.message.reply_text("⭐ 1 se 5 ke beech number bhejo."); return
        state[uid]={"action":"feedback_review","oid":oid,"rating":rating}
        await update.message.reply_text("📝 Short review bhejo, ya /skip.")
        return
    if action=="feedback_review":
        oid=s.get("oid"); rating=int(s.get("rating",0)); review=text.strip(); o=await db.get_order(oid)
        if o and o["customer_id"]==uid and o["status"]=="completed":
            dbx=await db.connect()
            await dbx.execute("UPDATE users SET rating_sum=rating_sum+?,rating_count=rating_count+1 WHERE id=?",(rating,uid))
            await dbx.execute("UPDATE orders SET notes=COALESCE(notes,'') || ?,updated_at=? WHERE id=?",("\nfeedback:"+str(rating)+":"+review,db.now(),oid))
            await dbx.commit(); await dbx.close(); state.pop(uid,None)
            await update.message.reply_text("🙏 <b>Thank you!</b>\n⭐ Rating & feedback save ho gaya.",parse_mode="HTML")
        return
    if action=="broadcast":
        if uid!=OWNER_ID:
            state.pop(uid,None); return
        state.pop(uid,None)
        dbx=await db.connect()
        cur=await dbx.execute("SELECT id FROM users")
        users=await cur.fetchall()
        await dbx.close()
        sent=failed=0
        for row in users:
            try:
                await context.bot.send_message(int(row["id"]),text)
                sent+=1
            except Exception:
                failed+=1
        await update.message.reply_text(f"📢 <b>Broadcast Complete</b>\n\n✅ Sent: {sent}\n❌ Failed: {failed}",parse_mode="HTML")
        return
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
        o=await db.get_order(oid)
        if not o or int(o["customer_id"]) != uid:
            state.pop(uid,None)
            await update.message.reply_text("❌ Order not found or unauthorized.")
            return
        assigned_admin = int(o["assigned_admin"] or 0)
        if not assigned_admin:
            state.pop(uid,None)
            await update.message.reply_text("⚠️ This order has no assigned Admin. Please contact support.")
            return
        await db.update_order(oid,payment_utr=text,payment_status="pending")
        await db.create_payment_pending(
            oid, text, o["total"],
            qr_admin_id=int(s.get("qr_admin_id") or assigned_admin),
            qr_value=s.get("qr_value") or "",
            qr_source=s.get("qr_source") or "assigned_admin"
        )
        state[uid]={"action":"payment_proof","oid":oid,"assigned_admin":assigned_admin}
        await update.message.reply_text(
            "📸 UTR saved. Ab payment screenshot bhejo.\n"
            "🔒 Payment verification sirf aapke assigned Admin ya Super Admin karega."
        )
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
    uid=update.effective_user.id
    s=state.get(uid,{})
    fid=update.message.photo[-1].file_id
    caption=(update.message.caption or "").strip()

    # Handle admin QR uploads here instead of a separate catch-all PHOTO handler.
    # PTB processes only the first matching handler in a group; the old QR handler
    # was matching every photo and preventing customer cart screenshots from
    # reaching the screenshot handler.
    if uid==OWNER_ID and s.get("action")=="qr_admin_upload":
        aid=int(s["admin_id"])
        await db.set_admin_qr(aid,fid,True)
        state.pop(uid,None)
        await update.message.reply_text(f"✅ Admin QR saved successfully for Admin {aid}.")
        return

    if uid==OWNER_ID and (s.get("action")=="qr_upload" or caption.lower().startswith("/setqr")):
        await db.set_setting("default_qr",fid)
        state.pop(uid,None)
        await update.message.reply_text("✅ Default Palace QR image saved successfully.")
        return

    if not s:
        return

    action=s["action"]; oid=s.get("oid")
    if action=="screenshot":
        await db.update_order(oid,cart_screenshot=fid,status="screenshot_received"); state.pop(uid,None)
        await update.message.reply_text(f"📸 {oid} screenshot received. Palace Admin will verify cart and enter actual Swiggy price.")
        o=await db.get_order(oid); aid=int(o["assigned_admin"] or await db.get_customer_admin(uid) or OWNER_ID)
        if aid:
            try: await context.bot.send_message(aid,f"📥 New cart screenshot for {oid} from customer {uid}. Open Admin Panel with /admin.")
            except: pass
    elif action=="payment_proof":
        o=await db.get_order(oid)
        if not o or int(o["customer_id"]) != uid:
            state.pop(uid,None)
            await update.message.reply_text("❌ Order not found or unauthorized.")
            return
        await db.set_payment_proof(oid, fid)
        state.pop(uid,None)
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
        # Store the priority payment first, then send the assigned Admin a
        # real approve/reject keyboard. Previously the payment was stored but
        # no admin action buttons were sent, so High Priority could never be
        # activated from the normal flow.
        dbx=await db.connect()
        await dbx.execute(
            "INSERT INTO priority_payments(customer_id,amount,utr,proof,created_at,status) VALUES(?,?,?,?,?,?)",
            (uid,s["fee"],s["utr"],fid,db.now(),"pending")
        )
        await dbx.commit()
        await dbx.close()
        state.pop(uid,None)
        await update.message.reply_text("⭐ Priority payment received. Admin verification pending.")
        aid=int(s.get("admin_id") or await db.get_customer_admin(uid) or OWNER_ID)
        if aid:
            try:
                customer = await db.get_user(uid)
                cname = (customer["first_name"] if customer else "") or (customer["username"] if customer else "") or f"Telegram {uid}"
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Approve Priority",callback_data=f"prioapprove:{uid}"),
                    InlineKeyboardButton("❌ Reject",callback_data=f"prioreject:{uid}")
                ]])
                await context.bot.send_photo(
                    aid,
                    fid,
                    caption=(
                        "⭐ <b>HIGH PRIORITY PAYMENT PENDING</b>\n\n"
                        f"👤 Customer: <b>{cname}</b>\n"
                        f"🆔 Telegram ID: <code>{uid}</code>\n"
                        f"💰 Amount: ₹{float(s['fee']):.0f}\n"
                        f"🧾 UTR: <code>{s['utr']}</code>"
                    ),
                    parse_mode="HTML",
                    reply_markup=kb
                )
            except Exception:
                log.exception("Failed to send priority verification to admin=%s customer=%s", aid, uid)

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
        await update.message.reply_text("📷 Send a QR photo from Admin Panel.\n\n🔳 /setqr is no longer needed.")
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

telegram_ready=False
polling_active=False

async def health(request):
    if not telegram_ready:
        return PlainTextResponse("NOT READY", status_code=503)
    return PlainTextResponse("OK")

async def telegram_webhook(request):
    if request.method != "POST":
        return PlainTextResponse("Method Not Allowed", status_code=405)
    try:
        payload = await request.json()
        update = Update.de_json(payload, app_global.bot)
        if update is not None:
            await app_global.update_queue.put(update)
        return JSONResponse({"ok": True})
    except Exception:
        log.exception("Webhook update handling failed")
        # Return 200 so Telegram does not create a retry storm for malformed/duplicate deliveries.
        return JSONResponse({"ok": True})

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")

    await db.init_db()
    await db.ensure_bootstrap_admins(ADMIN_IDS)
    log.info("Database initialized")

    app=Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()
    global app_global
    app_global=app

    # Register every Telegram handler before polling starts.
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("ping",ping_cmd))
    app.add_handler(CommandHandler("admin",admin_cmd))
    app.add_handler(CommandHandler("forcejoin_add",forcejoin_add_cmd))
    app.add_handler(CommandHandler("forcejoin_remove",forcejoin_remove_cmd))
    app.add_handler(CommandHandler("addadmin",addadmin_cmd))
    app.add_handler(CommandHandler("removeadmin",removeadmin_cmd))
    app.add_handler(CommandHandler("price",price_cmd))
    app.add_handler(CommandHandler("swiggyid",swiggyid_cmd))
    app.add_handler(CommandHandler("setcharge",setcharge))
    app.add_handler(CommandHandler("setpriority",setpriority))
    app.add_handler(CommandHandler("setbusiness",setbusiness))
    app.add_handler(CommandHandler("setqr",setqr))
    app.add_handler(CommandHandler("cancel",cancel_cmd))
    app.add_handler(CommandHandler("feedback",feedback_cmd))
    app.add_handler(CommandHandler("skip",skip_cmd))
    app.add_handler(CallbackQueryHandler(seller_entry_callback, pattern=r"^become_seller$"))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND,photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_error_handler(error)

    async def post_init(application):
        await application.bot.set_my_commands([
            ("start","🏰 Start Swiggy Palace"),
            ("ping","⚡ Bot status"),
            ("admin","👑 Admin Panel"),
            ("feedback","⭐ Order Feedback")
        ])

    # Run Telegram and the Render HTTP server in one process using webhook delivery.
    # This eliminates competing getUpdates pollers and the Telegram 409 Conflict problem.
    from uvicorn import Config, Server
    web=Starlette(routes=[
        Route("/health",health, methods=["GET"]),
        Route("/telegram/webhook",telegram_webhook, methods=["POST"])
    ])
    server=Server(Config(web,host="0.0.0.0",port=PORT,log_level="info"))
    health_task=asyncio.create_task(server.serve())

    try:
        global telegram_ready, polling_active
        telegram_ready=False
        polling_active=False
        await app.initialize()
        me=await app.bot.get_me()
        log.info("Telegram bot connected as @%s (%s)", me.username, me.id)

        await post_init(app)
        await app.start()

        webhook_base = os.getenv("WEBHOOK_URL", "").strip().rstrip("/")
        if not webhook_base:
            webhook_base = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
        if not webhook_base:
            raise RuntimeError("WEBHOOK_URL or RENDER_EXTERNAL_URL is required for webhook mode")

        webhook_url = webhook_base + "/telegram/webhook"
        # Register webhook with retries so transient startup errors do not
        # leave the bot silently disconnected.
        last_webhook_error = None
        for attempt in range(1, 6):
            try:
                await app.bot.set_webhook(
                    url=webhook_url,
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=False
                )
                last_webhook_error = None
                break
            except Exception as exc:
                last_webhook_error = exc
                log.exception("Webhook registration attempt %s/5 failed", attempt)
                await asyncio.sleep(min(attempt * 2, 10))
        if last_webhook_error is not None:
            raise RuntimeError(f"Webhook registration failed after 5 attempts: {last_webhook_error}")
        polling_active=True
        telegram_ready=True
        log.info("Telegram webhook is ACTIVE: %s", webhook_url)

        await asyncio.Event().wait()
    except Exception:
        log.exception("Telegram bot startup/runtime failure")
        raise
    finally:
        # Keep the webhook registered during shutdown. This is important on
        # Render restarts/free-instance wakeups.
        log.info("Keeping Telegram webhook registered during shutdown.")
        try:
            if app.running:
                await app.stop()
        except Exception:
            log.exception("Failed to stop Telegram application cleanly")
        try:
            if app.initialized:
                await app.shutdown()
        except Exception:
            log.exception("Failed to shutdown Telegram application cleanly")
        if not health_task.done():
            health_task.cancel()
            try:
                await health_task
            except asyncio.CancelledError:
                pass

if __name__=="__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
