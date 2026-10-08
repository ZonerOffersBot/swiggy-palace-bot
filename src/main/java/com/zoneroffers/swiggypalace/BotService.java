package com.zoneroffers.swiggypalace;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import java.util.*;
import java.util.concurrent.*;

@Service
public class BotService {
 private static final Logger log=LoggerFactory.getLogger(BotService.class);
 private final TelegramApi tg; private final JdbcStore db; private final BotProperties props; private final ObjectMapper mapper;
 private final ExecutorService workers=Executors.newFixedThreadPool(8);
 public BotService(TelegramApi tg,JdbcStore db,BotProperties props,ObjectMapper mapper){this.tg=tg;this.db=db;this.props=props;this.mapper=mapper;}

 @PostConstruct public void start(){
  if(props.getToken().isBlank()){log.warn("BOT_TOKEN missing; Telegram disabled");return;}
  String base=props.getWebhookUrl();
  if(base.isBlank())base=System.getenv("RENDER_EXTERNAL_URL");
  if(base==null||base.isBlank()){log.warn("WEBHOOK_URL/RENDER_EXTERNAL_URL missing");return;}
  String url=base.replaceAll("/+$","")+"/telegram/webhook";
  try{tg.setWebhook(url);log.info("Telegram webhook registered: {}",url);}catch(Exception e){log.error("Webhook registration failed",e);}
 }

 public void accept(JsonNode update){
  long id=update.path("update_id").asLong(-1);
  if(id>=0&&!db.claimUpdate(id))return;
  workers.submit(()->{try{handle(update);}catch(Exception e){log.error("Unhandled Telegram update {}",id,e);}});
 }

 private void handle(JsonNode u){
  if(u.has("callback_query"))handleCallback(u.get("callback_query"));
  else if(u.has("message"))handleMessage(u.get("message"));
 }

 private void handleMessage(JsonNode m){
  JsonNode f=m.path("from"),c=m.path("chat");long uid=f.path("id").asLong(),chat=c.path("id").asLong();String text=m.path("text").asText("");
  db.upsertUser(uid,f.path("username").asText(""),f.path("first_name").asText(""));
  if(text.equals("/start")||text.startsWith("/start ")){send(chat,db.isAdmin(uid)?"👑 <b>Swiggy Palace Admin</b>\n\nSelect an option:":"🏰 <b>Swiggy Palace</b>\n\nWelcome! Choose an option:",db.isAdmin(uid)?adminMenu():customerMenu());return;}
  if(text.equals("/admin")){if(!db.isAdmin(uid))send(chat,"🔒 Admin access only.","");else send(chat,"👑 <b>Admin Panel</b>",adminMenu());return;}
  if(text.equals("/health")){send(chat,"✅ Bot is online.","");return;}
  if(text.equals("/help")){send(chat,"ℹ️ Use /start to open the menu.","");}
 }

 private void handleCallback(JsonNode q){
  String id=q.path("id").asText(""),data=q.path("data").asText("");long uid=q.path("from").path("id").asLong(),chat=q.path("message").path("chat").path("id").asLong();
  tg.answerCallback(id);
  if(data.startsWith("a_")&&!db.isAdmin(uid)){send(chat,"🔒 Admin access only.","");return;}
  try{
   switch(data){
    case "a_back"->send(chat,"👑 <b>Admin Panel</b>",adminMenu());
    case "a_stats"->send(chat,formatStats(),back());
    case "a_new"->send(chat,orders("📥 <b>NEW ORDERS</b>",db.orderIds("SELECT id FROM orders WHERE status IN ('new','address_received','cart_received','screenshot_received','price_confirmed') ORDER BY priority DESC,created_at ASC LIMIT 20")),back());
    case "a_active"->send(chat,orders("📦 <b>ACTIVE ORDERS</b>",db.orderIds("SELECT id FROM orders WHERE status NOT IN ('completed','cancelled','refund_completed') ORDER BY priority DESC,updated_at DESC LIMIT 20")),back());
    case "a_pay","a_receive"->send(chat,"💳 <b>PAYMENTS</b>\n\nPending: <b>"+db.pendingPayments()+"</b>",back());
    case "a_support"->send(chat,"🎫 <b>HELP & SUPPORT</b>\n\nOpen tickets: <b>"+db.supportTickets()+"</b>",back());
    case "a_admins"->send(chat,"👨‍💼 <b>ADMIN MANAGEMENT</b>\n\n"+String.join("\n",db.admins()),back());
    case "a_charges"->send(chat,"💰 <b>CHARGES</b>\n\nCharge controls remain stored in the existing database.",back());
    case "a_forcejoin"->send(chat,"📢 <b>FORCE JOIN</b>\n\nExisting force-join settings are preserved. Management controls will be migrated with the order workflow.",back());
    case "a_qr"->send(chat,"📷 <b>PAYMENT QR</b>\n\nExisting QR settings are preserved in the database.",back());
    case "a_settings"->send(chat,"⚙️ <b>SETTINGS</b>\n\nWebhook: ✅\nDuplicate-update guard: ✅\nSQLite WAL: ✅\nWorker isolation: ✅",back());
    case "a_broadcast"->send(chat,"📢 <b>BROADCAST</b>\n\nBroadcast UI is queued for the next migration phase.",back());
    case "a_search"->send(chat,"🔎 <b>SEARCH ID</b>\n\nSearch UI is queued for the next migration phase.",back());
    case "new_order"->send(chat,"🛒 New order flow is ready for the full migration.",customerMenu());
    case "priority"->send(chat,"⭐ Priority service flow is ready for the full migration.",customerMenu());
    case "my_orders"->send(chat,"📦 Your order list will use the existing orders database.",customerMenu());
    case "profile"->send(chat,"👤 Your profile is stored in the existing users database.",customerMenu());
    case "help_support"->send(chat,"🆘 Send your support query here after the support workflow migration.",customerMenu());
    default->send(chat,"⚠️ Unknown action. Please reopen the menu.",db.isAdmin(uid)?adminMenu():customerMenu());
   }
  }catch(Exception e){log.error("Callback failed data={}",data,e);send(chat,"⚠️ Temporary error. Please try again.",db.isAdmin(uid)?adminMenu():customerMenu());}
 }

 private String formatStats(){
  Map<String,Object>s=db.stats();
  return "📊 <b>Palace Stats</b>\n\n👥 Customers: "+s.get("customers")+"\n📦 Orders: "+s.get("orders")+"\n🏁 Completed: "+s.get("completed")+"\n⏳ Active: "+s.get("active")+"\n🍔 Swiggy Value: ₹"+String.format(Locale.US,"%.2f",((Number)s.get("swiggy")).doubleValue())+"\n💰 Palace Charges: ₹"+String.format(Locale.US,"%.2f",((Number)s.get("charges")).doubleValue())+"\n↩️ Refunds: ₹"+String.format(Locale.US,"%.2f",((Number)s.get("refunds")).doubleValue());
 }
 private String orders(String title,List<String>ids){return ids.isEmpty()?title+"\n\nNo orders found.":title+"\n\n"+String.join("\n",ids);}
 private String customerMenu(){return markupRows(List.of(row(button("🛒 Place New Order","new_order")),row(button("⭐ Become High Priority","priority")),row(button("📦 My Orders","my_orders"),button("👤 My Profile","profile")),row(button("🆘 Help & Support","help_support"))));}
 private String adminMenu(){return markup(row(button("📥 New Orders","a_new"),button("💳 Payments","a_pay")),row(button("📥 Payment Receive","a_receive")),row(button("📦 Active Orders","a_active"),button("📊 Stats","a_stats")),row(button("👨‍💼 Admins","a_admins"),button("💰 Charges","a_charges")),row(button("🎫 Help & Support","a_support")),row(button("📢 Broadcast","a_broadcast")),row(button("🔎 Search ID","a_search")),row(button("📢 Force Join","a_forcejoin")),row(button("📷 Payment QR","a_qr"),button("⚙️ Settings","a_settings")));}
 private String back(){return markup(row(button("⬅️ Back","a_back")));}
 private Map<String,String> button(String text,String data){return Map.of("text",text,"callback_data",data);}
 @SafeVarargs private final List<Map<String,String>> row(Map<String,String>...b){return Arrays.asList(b);}
 private String markupRows(List<List<Map<String,String>>> rows){try{return mapper.writeValueAsString(Map.of("inline_keyboard",rows));}catch(Exception e){throw new RuntimeException(e);}}
 private String markup(List<Map<String,String>>...rows){try{return mapper.writeValueAsString(Map.of("inline_keyboard",Arrays.asList(rows)));}catch(Exception e){throw new RuntimeException(e);}}
 private void send(long chat,String text,String markup){try{tg.sendMessage(chat,text,markup);}catch(Exception e){log.error("sendMessage failed chat={}",chat,e);}}
}
