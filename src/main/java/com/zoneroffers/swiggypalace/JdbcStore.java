package com.zoneroffers.swiggypalace;
import org.springframework.stereotype.Service;
import jakarta.annotation.PostConstruct;
import java.sql.*;
import java.time.Instant;
import java.util.*;

@Service
public class JdbcStore {
 private final BotProperties props;
 public JdbcStore(BotProperties props){this.props=props;}
 private Connection connection() throws SQLException{
  Connection c=DriverManager.getConnection("jdbc:sqlite:"+props.getDatabasePath());
  try(Statement s=c.createStatement()){s.execute("PRAGMA busy_timeout=5000");s.execute("PRAGMA journal_mode=WAL");s.execute("PRAGMA synchronous=NORMAL");}
  return c;
 }
 @PostConstruct public void init(){
  String[] schema={
   "CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT DEFAULT '',first_name TEXT DEFAULT '',role TEXT DEFAULT '',public_id TEXT UNIQUE,created_at TEXT,last_seen TEXT)",
   "CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,customer_id INTEGER NOT NULL,address_link TEXT,cart_link TEXT,cart_screenshot TEXT,swiggy_amount REAL DEFAULT 0,palace_charge REAL DEFAULT 0,priority_fee REAL DEFAULT 0,adjustment REAL DEFAULT 0,total REAL DEFAULT 0,payment_status TEXT DEFAULT 'pending',payment_utr TEXT,status TEXT DEFAULT 'new',priority INTEGER DEFAULT 0,assigned_admin INTEGER,swiggy_order_id TEXT,notes TEXT,created_at TEXT,updated_at TEXT)",
   "CREATE TABLE IF NOT EXISTS payments(order_id TEXT PRIMARY KEY,utr TEXT,amount REAL DEFAULT 0,proof TEXT,status TEXT DEFAULT 'pending',verified_by INTEGER,created_at TEXT,updated_at TEXT)",
   "CREATE TABLE IF NOT EXISTS refunds(id INTEGER PRIMARY KEY AUTOINCREMENT,order_id TEXT UNIQUE,amount REAL,reason TEXT,status TEXT DEFAULT 'pending',created_at TEXT,updated_at TEXT)",
   "CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY AUTOINCREMENT,customer_id INTEGER,subject TEXT,status TEXT DEFAULT 'open',created_at TEXT)",
   "CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)",
   "CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY,role TEXT DEFAULT 'order_admin',display_name TEXT DEFAULT '',qr_value TEXT DEFAULT '',qr_enabled INTEGER DEFAULT 1,active INTEGER DEFAULT 1,created_at TEXT,updated_at TEXT)",
   "CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT,actor_id INTEGER,action TEXT,order_id TEXT,details TEXT,created_at TEXT)",
   "CREATE TABLE IF NOT EXISTS customer_admins(customer_id INTEGER PRIMARY KEY,admin_id INTEGER NOT NULL,active INTEGER DEFAULT 1,created_at TEXT,updated_at TEXT)",
   "CREATE TABLE IF NOT EXISTS second_order_unlocks(customer_id INTEGER PRIMARY KEY,paid_amount REAL DEFAULT 0,utr TEXT,proof TEXT,status TEXT DEFAULT 'pending',verified_by INTEGER,created_at TEXT,updated_at TEXT)",
   "CREATE TABLE IF NOT EXISTS processed_updates(update_id INTEGER PRIMARY KEY,processed_at TEXT NOT NULL)"
  };
  try(Connection c=connection()){
   try(Statement s=c.createStatement()){for(String sql:schema)s.execute(sql);}
   try(PreparedStatement p=c.prepareStatement("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)")){
    for(String[] d:new String[][]{{"palace_charge","30"},{"palace_charge_enabled","1"},{"priority_fee","49"},{"business_open","on"},{"default_qr",""},{"force_join_channels","@Swiggypalace"}}){p.setString(1,d[0]);p.setString(2,d[1]);p.addBatch();}p.executeBatch();
   }
   try(PreparedStatement p=c.prepareStatement("INSERT OR IGNORE INTO admins(id,role,display_name,created_at,updated_at) VALUES(?,?,?,?,?)")){
    String now=Instant.now().toString();Set<Long> ids=new LinkedHashSet<>();if(props.getOwnerId()!=0)ids.add(props.getOwnerId());
    for(String x:props.getAdminIds().split(","))try{if(!x.isBlank())ids.add(Long.parseLong(x.trim()));}catch(Exception ignored){}
    for(long id:ids){p.setLong(1,id);p.setString(2,"order_admin");p.setString(3,"");p.setString(4,now);p.setString(5,now);p.addBatch();}p.executeBatch();
   }
  }catch(SQLException e){throw new IllegalStateException("Database initialization failed",e);}
 }
 public boolean isAdmin(long id){try(Connection c=connection();PreparedStatement p=c.prepareStatement("SELECT active FROM admins WHERE id=?")){p.setLong(1,id);try(ResultSet r=p.executeQuery()){return r.next()&&r.getInt(1)==1;}}catch(SQLException e){throw new RuntimeException(e);}}
 public void upsertUser(long id,String u,String n){String now=Instant.now().toString();try(Connection c=connection();PreparedStatement p=c.prepareStatement("INSERT INTO users(id,username,first_name,created_at,last_seen) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name,last_seen=excluded.last_seen")){p.setLong(1,id);p.setString(2,u==null?"":u);p.setString(3,n==null?"":n);p.setString(4,now);p.setString(5,now);p.executeUpdate();}catch(SQLException e){throw new RuntimeException(e);}}
 private long scalar(Connection c,String sql)throws SQLException{try(Statement s=c.createStatement();ResultSet r=s.executeQuery(sql)){return r.next()?r.getLong(1):0;}}
 private double money(Connection c,String sql)throws SQLException{try(Statement s=c.createStatement();ResultSet r=s.executeQuery(sql)){return r.next()?r.getDouble(1):0;}}
 public Map<String,Object> stats(){try(Connection c=connection()){Map<String,Object>m=new LinkedHashMap<>();m.put("customers",scalar(c,"SELECT COUNT(*) FROM users"));m.put("orders",scalar(c,"SELECT COUNT(*) FROM orders"));m.put("completed",scalar(c,"SELECT COUNT(*) FROM orders WHERE status='completed'"));m.put("active",scalar(c,"SELECT COUNT(*) FROM orders WHERE status NOT IN ('completed','cancelled','refund_completed')"));m.put("swiggy",money(c,"SELECT COALESCE(SUM(swiggy_amount),0) FROM orders"));m.put("charges",money(c,"SELECT COALESCE(SUM(palace_charge+priority_fee+adjustment),0) FROM orders"));m.put("refunds",money(c,"SELECT COALESCE(SUM(amount),0) FROM refunds WHERE status IN ('processed','completed')"));return m;}catch(SQLException e){throw new RuntimeException(e);}}
 public List<String> orderIds(String sql){List<String>o=new ArrayList<>();try(Connection c=connection();Statement s=c.createStatement();ResultSet r=s.executeQuery(sql)){while(r.next())o.add(r.getString(1));return o;}catch(SQLException e){throw new RuntimeException(e);}}
 public int pendingPayments(){try(Connection c=connection()){return (int)scalar(c,"SELECT COUNT(*) FROM payments WHERE status='pending'");}catch(SQLException e){throw new RuntimeException(e);}}
 public int supportTickets(){try(Connection c=connection()){return (int)scalar(c,"SELECT COUNT(*) FROM tickets WHERE status='open'");}catch(SQLException e){throw new RuntimeException(e);}}
 public List<String> admins(){List<String>o=new ArrayList<>();try(Connection c=connection();Statement s=c.createStatement();ResultSet r=s.executeQuery("SELECT id,role,display_name FROM admins WHERE active=1 ORDER BY id")){while(r.next())o.add(r.getLong(1)+" • "+r.getString(2)+(r.getString(3)==null||r.getString(3).isBlank()?"":" — "+r.getString(3)));return o;}catch(SQLException e){throw new RuntimeException(e);}}
 public boolean claimUpdate(long id){try(Connection c=connection();PreparedStatement p=c.prepareStatement("INSERT OR IGNORE INTO processed_updates(update_id,processed_at) VALUES(?,?)")){p.setLong(1,id);p.setString(2,Instant.now().toString());return p.executeUpdate()==1;}catch(SQLException e){throw new RuntimeException(e);}}
}