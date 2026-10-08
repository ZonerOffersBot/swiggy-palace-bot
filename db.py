import aiosqlite
import sqlite3
import shutil
from pathlib import Path
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
 order_id TEXT PRIMARY KEY,
 utr TEXT,
 amount REAL DEFAULT 0,
 proof TEXT,
 status TEXT DEFAULT 'pending',
 verified_by INTEGER,
 approved_at TEXT,
 qr_admin_id INTEGER,
 qr_value TEXT,
 qr_source TEXT DEFAULT 'assigned_admin',
 created_at TEXT,
 updated_at TEXT
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
CREATE TABLE IF NOT EXISTS seller_requests(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL,
 full_name TEXT DEFAULT '', phone TEXT DEFAULT '', city TEXT DEFAULT '',
 experience TEXT DEFAULT '', upi TEXT DEFAULT '', business TEXT DEFAULT '',
 status TEXT DEFAULT 'pending', reviewed_by INTEGER, reviewed_at TEXT,
 created_at TEXT, updated_at TEXT
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
CREATE TABLE IF NOT EXISTS second_order_unlocks(
 customer_id INTEGER PRIMARY KEY,
 paid_amount REAL DEFAULT 0,
 utr TEXT,
 proof TEXT,
 status TEXT DEFAULT 'pending',
 verified_by INTEGER,
 created_at TEXT,
 updated_at TEXT
);
CREATE TABLE IF NOT EXISTS second_order_unlock_history(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 customer_id INTEGER NOT NULL,
 paid_amount REAL DEFAULT 0,
 utr TEXT,
 proof TEXT,
 status TEXT DEFAULT 'pending',
 verified_by INTEGER,
 created_at TEXT,
 updated_at TEXT
);
"""

async def connect():
    # DATA-SAFETY HARDENING:
    # - WAL + synchronous=FULL protects committed transactions.
    # - busy_timeout prevents transient lock failures from losing writes.
    # - foreign_keys stays enabled.
    # - No application code is allowed to delete business/audit rows.
    db_path = Path(DATABASE_PATH).expanduser()
    if db_path.parent != Path("."):
        db_path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(db_path), timeout=30)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA busy_timeout=30000")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA synchronous=FULL")
    await db.execute("PRAGMA wal_autocheckpoint=1000")
    return db


PROTECTED_TABLES = (
    "users", "orders", "payments", "priority_payments", "refunds",
    "tickets", "ticket_messages", "settings", "admins", "seller_requests",
    "audit_log", "customer_admins", "second_order_unlocks",
    "second_order_unlock_history"
)

async def backup_database(reason="startup"):
    """
    Create a point-in-time SQLite backup before schema/migration work.
    Old backups are never deleted by the bot.
    """
    src = Path(DATABASE_PATH).expanduser()
    if not src.exists() or src.stat().st_size == 0:
        return None

    backup_dir = src.parent / (src.name + ".backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    safe_reason = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(reason))
    target = backup_dir / f"{src.stem}_{stamp}_{safe_reason}.sqlite"

    # sqlite3 backup API is transaction-safe and includes committed WAL data.
    source = sqlite3.connect(str(src), timeout=30)
    dest = sqlite3.connect(str(target), timeout=30)
    try:
        source.execute("PRAGMA busy_timeout=30000")
        source.backup(dest)
        dest.commit()
    finally:
        dest.close()
        source.close()
    return str(target)

async def install_no_delete_guards(db):
    """
    Permanent database-level guard: normal bot code cannot DELETE records.
    This intentionally applies to business, payment, seller, support, admin,
    settings and audit tables. Corrections must use UPDATE/INSERT.
    """
    for table in PROTECTED_TABLES:
        trigger = "protect_delete_" + table
        await db.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {trigger}
            BEFORE DELETE ON {table}
            BEGIN
                SELECT RAISE(ABORT, 'DATA_DELETE_BLOCKED: {table} is append/protected');
            END;
            """
        )

async def init_db():

    db=await connect()
    await db.executescript(SCHEMA)
    migrations = (
        "ALTER TABLE users ADD COLUMN role TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN public_id TEXT",
        "ALTER TABLE payments ADD COLUMN approved_at TEXT",
        "ALTER TABLE payments ADD COLUMN qr_admin_id INTEGER",
        "ALTER TABLE payments ADD COLUMN qr_value TEXT",
        "ALTER TABLE payments ADD COLUMN qr_source TEXT DEFAULT 'assigned_admin'",
        "ALTER TABLE users ADD COLUMN priority INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN priority_paid INTEGER DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN priority INTEGER DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN tracking_link TEXT DEFAULT ''",
    )
    for sql in migrations:
        try:
            await db.execute(sql)
        except Exception:
            pass
    try:
        await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_public_id ON users(public_id)")
    except Exception:
        # Old databases may contain duplicate/legacy public IDs; do not crash bot startup.
        try:
            await db.execute("CREATE INDEX IF NOT EXISTS idx_users_public_id_fallback ON users(public_id)")
        except Exception:
            pass
    defaults={
      "palace_charge":"30","palace_charge_enabled":"1",
      "priority_fee":"49","priority_sla_minutes":"5",
      "business_open":"on","default_qr":"","force_join_channels":"@Swiggypalace","force_join_verified":""
    }
    for k,v in defaults.items():
        await db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))
    await db.commit()
    await db.close()

    # Keep a second snapshot after successful initialization/migrations.
    try:
        await backup_database("post_init")
    except Exception:
        pass

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

async def list_seller_requests(status=None):
    db=await connect()
    if status:
        cur=await db.execute("SELECT * FROM seller_requests WHERE status=? ORDER BY created_at DESC",(status,))
    else:
        cur=await db.execute("SELECT * FROM seller_requests ORDER BY created_at DESC")
    rows=await cur.fetchall(); await db.close(); return rows

async def create_seller_request(user_id, data):
    db=await connect()
    await db.execute("INSERT INTO seller_requests(user_id,full_name,phone,city,experience,upi,business,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(user_id,data.get('full_name',''),data.get('phone',''),data.get('city',''),data.get('experience',''),data.get('upi',''),data.get('business',''),'pending',now(),now()))
    await db.commit(); await db.close()

async def review_seller_request(request_id, status, reviewer_id):
    db=await connect()
    await db.execute("UPDATE seller_requests SET status=?,reviewed_by=?,reviewed_at=?,updated_at=? WHERE id=?",(status,reviewer_id,now(),now(),request_id))
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

async def second_order_fee():
    return float(await setting("second_order_fee","30"))

async def has_second_order_unlock(customer_id):
    db=await connect()
    cur=await db.execute("SELECT * FROM second_order_unlocks WHERE customer_id=? AND status='verified'",(customer_id,))
    row=await cur.fetchone(); await db.close(); return row

async def create_second_order_payment(customer_id, amount, utr="", proof=""):
    db=await connect()
    ts=now()
    # Append to immutable payment history first.
    await db.execute(
      "INSERT INTO second_order_unlock_history(customer_id,paid_amount,utr,proof,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
      (customer_id,amount,utr,proof,"pending",ts,ts)
    )
    # Keep the existing one-row-per-customer live state for compatibility.
    await db.execute(
      "INSERT INTO second_order_unlocks(customer_id,paid_amount,utr,proof,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?) "
      "ON CONFLICT(customer_id) DO UPDATE SET paid_amount=excluded.paid_amount,utr=excluded.utr,proof=excluded.proof,status='pending',verified_by=NULL,updated_at=excluded.updated_at",
      (customer_id,amount,utr,proof,"pending",ts,ts))
    await db.commit(); await db.close()

async def verify_second_order_unlock(customer_id, admin_id, ok):
    db=await connect()
    await db.execute("UPDATE second_order_unlocks SET status=?,verified_by=?,updated_at=? WHERE customer_id=? AND status='pending'",
                     ("verified" if ok else "rejected",admin_id,now(),customer_id))
    await db.commit(); await db.close()

async def consume_second_order_unlock(customer_id):
    # Preserve the payment/unlock audit record permanently. Never delete
    # customer financial/order history during normal bot operation.
    db=await connect()
    await db.execute(
        "UPDATE second_order_unlocks SET status='consumed',updated_at=? "
        "WHERE customer_id=? AND status='verified'",
        (now(),customer_id)
    )
    await db.commit(); await db.close()

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


async def create_payment_pending(order_id, utr, amount, qr_admin_id=None, qr_value="", qr_source="assigned_admin"):
    db = await connect()
    timestamp = now()
    await db.execute(
        """
        INSERT INTO payments(
            order_id, utr, amount, proof, status, verified_by,
            approved_at, qr_admin_id, qr_value, qr_source,
            created_at, updated_at
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(order_id) DO UPDATE SET
            utr=excluded.utr,
            amount=excluded.amount,
            proof=NULL,
            status='pending',
            verified_by=NULL,
            approved_at=NULL,
            qr_admin_id=excluded.qr_admin_id,
            qr_value=excluded.qr_value,
            qr_source=excluded.qr_source,
            updated_at=excluded.updated_at
        """,
        (
            order_id, str(utr).strip(), float(amount or 0), None, "pending",
            None, None, int(qr_admin_id) if qr_admin_id else None,
            qr_value or "", qr_source or "assigned_admin", timestamp, timestamp
        ),
    )
    await db.commit()
    await db.close()


async def set_payment_proof(order_id, proof):
    db = await connect()
    await db.execute(
        "UPDATE payments SET proof=?, status='pending', updated_at=? WHERE order_id=?",
        (proof, now(), order_id),
    )
    await db.commit()
    await db.close()


async def approve_payment_record(order_id, verifier_id, ok):
    db = await connect()
    status = "verified" if ok else "rejected"
    await db.execute(
        """
        UPDATE payments
        SET status=?, verified_by=?, approved_at=?, updated_at=?
        WHERE order_id=? AND status='pending'
        """,
        (status, verifier_id, now(), now(), order_id),
    )
    await db.commit()
    await db.close()


async def payment_record(order_id):
    db = await connect()
    cur = await db.execute("SELECT * FROM payments WHERE order_id=?", (order_id,))
    row = await cur.fetchone()
    await db.close()
    return row


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
