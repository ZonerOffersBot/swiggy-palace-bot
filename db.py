import aiosqlite
from datetime import datetime, timezone
from config import DATABASE_PATH

def now():
    return datetime.now(timezone.utc).isoformat()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
 id INTEGER PRIMARY KEY, username TEXT DEFAULT '', first_name TEXT DEFAULT '',
 role TEXT DEFAULT '', public_id TEXT UNIQUE,
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
CREATE TABLE IF NOT EXISTS admins(
 id INTEGER PRIMARY KEY,
 role TEXT DEFAULT 'order_admin',
 display_name TEXT DEFAULT '',
 qr_value TEXT DEFAULT '',
 qr_enabled INTEGER DEFAULT 1,
 active INTEGER DEFAULT 1,
 created_at TEXT,
 updated_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_log(
 id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER, action TEXT,
 order_id TEXT, details TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS customer_admins(
 customer_id INTEGER PRIMARY KEY,
 admin_id INTEGER NOT NULL,
 active INTEGER DEFAULT 1,
 created_at TEXT,
 updated_at TEXT
);
"""

async def connect():
    db=await aiosqlite.connect(DATABASE_PATH)
    db.row_factory=aiosqlite.Row
    return db

async def init_db():
    db=await connect()
    await db.executescript(SCHEMA)
    for sql in ("ALTER TABLE users ADD COLUMN role TEXT DEFAULT ''", "ALTER TABLE users ADD COLUMN public_id TEXT"):
        try: await db.execute(sql)
        except Exception: pass
    await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_public_id ON users(public_id)")
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

async def assign_public_id(uid, role):
    prefix="CUST" if role=="customer" else "SELL"
    db=await connect()
    cur=await db.execute("SELECT public_id FROM users WHERE id=?",(uid,))
    row=await cur.fetchone()
    if row and row["public_id"]:
        await db.close()
        return row["public_id"]
    cur=await db.execute("SELECT public_id FROM users WHERE role=? AND public_id IS NOT NULL ORDER BY rowid DESC LIMIT 1",(role,))
    row=await cur.fetchone()
    try: n=int(str(row["public_id"]).split("-")[-1])+1 if row else 1
    except Exception: n=1
    public_id=f"SP-{prefix}-{n:04d}"
    await db.execute("UPDATE users SET role=?,public_id=? WHERE id=?",(role,public_id,uid))
    await db.commit(); await db.close()
    return public_id

async def get_user_by_public_id(public_id):
    db=await connect()
    cur=await db.execute("SELECT * FROM users WHERE public_id=?",(public_id.strip().upper(),))
    row=await cur.fetchone(); await db.close(); return row

async def get_user(uid):
    db=await connect()
    cur=await db.execute("SELECT * FROM users WHERE id=?",(uid,))
    row=await cur.fetchone(); await db.close(); return row

async def setting(key,default=None):
    db=await connect(); cur=await db.execute("SELECT value FROM settings WHERE key=?",(key,))
    row=await cur.fetchone(); await db.close()
    return row["value"] if row else default

async def set_setting(key,value):
    db=await connect()
    await db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,str(value)))
    await db.commit(); await db.close()

async def is_db_admin(uid):
    db=await connect(); cur=await db.execute("SELECT active FROM admins WHERE id=?",(uid,))
    row=await cur.fetchone(); await db.close()
    return bool(row and row["active"])

async def ensure_bootstrap_admins(admin_ids):
    db=await connect()
    for aid in admin_ids:
        await db.execute("INSERT OR IGNORE INTO admins(id,role,display_name,created_at,updated_at) VALUES(?,?,?,?,?)",(aid,"order_admin","",now(),now()))
    await db.commit(); await db.close()

async def list_admins():
    db=await connect(); cur=await db.execute("SELECT * FROM admins WHERE active=1 ORDER BY id")
    rows=await cur.fetchall(); await db.close(); return rows

async def get_admin(aid):
    db=await connect(); cur=await db.execute("SELECT * FROM admins WHERE id=?",(aid,))
    row=await cur.fetchone(); await db.close(); return row

async def add_admin(aid,role="order_admin",name=""):
    db=await connect()
    await db.execute("""INSERT INTO admins(id,role,display_name,created_at,updated_at)
        VALUES(?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET role=excluded.role,display_name=excluded.display_name,active=1,updated_at=excluded.updated_at""",
        (aid,role,name,now(),now()))
    await db.commit(); await db.close()

async def remove_admin(aid):
    db=await connect(); await db.execute("UPDATE admins SET active=0,updated_at=? WHERE id=?",(now(),aid)); await db.commit(); await db.close()

async def set_admin_qr(aid,value,enabled=True):
    db=await connect(); await db.execute("UPDATE admins SET qr_value=?,qr_enabled=?,updated_at=? WHERE id=?",(value,1 if enabled else 0,now(),aid)); await db.commit(); await db.close()

async def get_customer_admin(customer_id):
    db=await connect()
    cur=await db.execute("SELECT admin_id FROM customer_admins WHERE customer_id=? AND active=1",(customer_id,))
    row=await cur.fetchone(); await db.close()
    return int(row["admin_id"]) if row else None

async def assign_customer_admin(customer_id):
    existing=await get_customer_admin(customer_id)
    if existing:
        return existing
    db=await connect()
    cur=await db.execute("SELECT id FROM admins WHERE active=1 ORDER BY id LIMIT 1")
    row=await cur.fetchone()
    aid=int(row["id"]) if row else 0
    if not aid:
        await db.close()
        return 0
    await db.execute(
      "INSERT INTO customer_admins(customer_id,admin_id,active,created_at,updated_at) VALUES(?,?,?,?,?) "
      "ON CONFLICT(customer_id) DO UPDATE SET admin_id=excluded.admin_id,active=1,updated_at=excluded.updated_at",
      (customer_id,aid,1,now(),now()))
    await db.commit(); await db.close()
    return aid

async def set_order_admin(oid, admin_id):
    await update_order(oid, assigned_admin=admin_id)
    return admin_id

async def payment_qr_for(customer_id, order_id=None):
    aid=await get_customer_admin(customer_id)
    if order_id:
        o=await get_order(order_id)
        if o and o["assigned_admin"]:
            aid=int(o["assigned_admin"])
    if aid:
        a=await get_admin(aid)
        if a and a["active"] and a["qr_enabled"] and a["qr_value"]:
            return a["qr_value"], aid
    return await setting("default_qr",""), aid or 0

async def has_unfinished_order(customer_id):
    db=await connect()
    cur=await db.execute("SELECT id,status FROM orders WHERE customer_id=? AND status NOT IN ('completed','cancelled','refund_completed') ORDER BY created_at DESC LIMIT 1",(customer_id,))
    row=await cur.fetchone(); await db.close(); return row

async def create_order(customer_id):
    assigned=await assign_customer_admin(customer_id)
    db=await connect()
    cur=await db.execute("SELECT id FROM orders ORDER BY rowid DESC LIMIT 1")
    row=await cur.fetchone()
    n=1000 if not row else int(str(row["id"]).split("-")[-1])+1
    oid=f"SP-{n}"
    await db.execute("INSERT INTO orders(id,customer_id,assigned_admin,created_at,updated_at) VALUES(?,?,?,?,?)",(oid,customer_id,assigned or None,now(),now()))
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
