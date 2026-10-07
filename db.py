import aiosqlite
from datetime import datetime, timezone
from config import DATABASE_PATH

def now():
    return datetime.now(timezone.utc).isoformat()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
 id INTEGER PRIMARY KEY, username TEXT DEFAULT '', first_name TEXT DEFAULT '',
 rating_sum INTEGER DEFAULT 0, rating_count INTEGER DEFAULT 0,
 warnings INTEGER DEFAULT 0, priority INTEGER DEFAULT 0, priority_paid INTEGER DEFAULT 0,
 created_at TEXT, last_seen TEXT
);
CREATE TABLE IF NOT EXISTS orders(
 id TEXT PRIMARY KEY, customer_id INTEGER NOT NULL,
 address_link TEXT, cart_link TEXT, cart_screenshot TEXT,
 swiggy_amount REAL DEFAULT 0, palace_charge REAL DEFAULT 0,
 priority_fee REAL DEFAULT 0, adjustment REAL DEFAULT 0, total REAL DEFAULT 0,
 payment_status TEXT DEFAULT 'pending', payment_utr TEXT,
 status TEXT DEFAULT 'new', priority INTEGER DEFAULT 0,
 assigned_admin INTEGER, swiggy_order_id TEXT, notes TEXT,
 created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS payments(
 order_id TEXT PRIMARY KEY, utr TEXT, amount REAL DEFAULT 0, proof TEXT,
 status TEXT DEFAULT 'pending', verified_by INTEGER,
 created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS priority_payments(
 id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, amount REAL,
 utr TEXT, proof TEXT, status TEXT DEFAULT 'pending', verified_by INTEGER,
 created_at TEXT
);
CREATE TABLE IF NOT EXISTS refunds(
 id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT UNIQUE, amount REAL,
 reason TEXT, status TEXT DEFAULT 'pending', created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS tickets(
 id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, subject TEXT,
 status TEXT DEFAULT 'open', created_at TEXT
);
CREATE TABLE IF NOT EXISTS ticket_messages(
 id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER, sender_id INTEGER,
 body TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS audit_log(
 id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER, action TEXT,
 order_id TEXT, details TEXT, created_at TEXT
);
"""

async def connect():
    db=await aiosqlite.connect(DATABASE_PATH)
    db.row_factory=aiosqlite.Row
    return db

async def init_db():
    db=await connect()
    await db.executescript(SCHEMA)
    defaults={
      "palace_charge":"30","palace_charge_enabled":"1",
      "priority_fee":"49","priority_sla_minutes":"5",
      "business_open":"on","default_qr":""
    }
    for k,v in defaults.items():
        await db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))
    await db.commit(); await db.close()

async def upsert_user(user):
    db=await connect()
    await db.execute(
      """INSERT INTO users(id,username,first_name,created_at,last_seen)
         VALUES(?,?,?,?,?)
         ON CONFLICT(id) DO UPDATE SET username=excluded.username,
         first_name=excluded.first_name,last_seen=excluded.last_seen""",
      (user.id,user.username or "",user.first_name or "",now(),now())
    )
    await db.commit(); await db.close()

async def setting(key,default=None):
    db=await connect(); cur=await db.execute("SELECT value FROM settings WHERE key=?",(key,))
    row=await cur.fetchone(); await db.close()
    return row["value"] if row else default

async def set_setting(key,value):
    db=await connect()
    await db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,str(value)))
    await db.commit(); await db.close()

async def create_order(customer_id):
    db=await connect()
    cur=await db.execute("SELECT id FROM orders ORDER BY rowid DESC LIMIT 1")
    row=await cur.fetchone()
    n=1000 if not row else int(str(row["id"]).split("-")[-1])+1
    oid=f"SP-{n}"
    await db.execute("INSERT INTO orders(id,customer_id,created_at,updated_at) VALUES(?,?,?,?)",(oid,customer_id,now(),now()))
    await db.commit(); await db.close()
    return oid

async def get_order(oid):
    db=await connect(); cur=await db.execute("SELECT * FROM orders WHERE id=?",(oid,))
    row=await cur.fetchone(); await db.close(); return row

async def update_order(oid,**fields):
    allowed={"address_link","cart_link","cart_screenshot","swiggy_amount","palace_charge",
      "priority_fee","adjustment","total","payment_status","payment_utr","status",
      "priority","assigned_admin","swiggy_order_id","notes"}
    fields={k:v for k,v in fields.items() if k in allowed}
    if not fields:return
    fields["updated_at"]=now()
    sets=", ".join(f"{k}=?" for k in fields); values=list(fields.values())+[oid]
    db=await connect(); await db.execute(f"UPDATE orders SET {sets} WHERE id=?",values)
    await db.commit(); await db.close()

async def stats():
    db=await connect()
    async def scalar(sql):
        cur=await db.execute(sql); r=await cur.fetchone(); return r[0] or 0
    out={
      "customers":await scalar("SELECT COUNT(*) FROM users"),
      "orders":await scalar("SELECT COUNT(*) FROM orders"),
      "completed":await scalar("SELECT COUNT(*) FROM orders WHERE status='completed'"),
      "active":await scalar("SELECT COUNT(*) FROM orders WHERE status NOT IN ('completed','cancelled','refund_completed')"),
      "swiggy":await scalar("SELECT COALESCE(SUM(swiggy_amount),0) FROM orders"),
      "charges":await scalar("SELECT COALESCE(SUM(palace_charge+priority_fee+adjustment),0) FROM orders"),
      "refunds":await scalar("SELECT COALESCE(SUM(amount),0) FROM refunds WHERE status IN ('processed','completed')")
    }
    await db.close(); return out

async def audit(actor_id,action,order_id=None,details=""):
    db=await connect(); await db.execute(
      "INSERT INTO audit_log(actor_id,action,order_id,details,created_at) VALUES(?,?,?,?,?)",
      (actor_id,action,order_id,details,now()))
    await db.commit(); await db.close()
