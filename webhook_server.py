import hashlib
import hmac
import json
import logging
import time
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response

from config import BOT_TOKEN
from db import db
from services_phonepe import verify_webhook_signature
from utils import is_admin
from feature_controls import FEATURES, FEATURE_KEYS, MASTER_KEY

log = logging.getLogger(__name__)
app = FastAPI()
STATIC_DIR = Path(__file__).parent / "admin_webapp"

def validate_init_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(status_code=401, detail="Telegram session required")
    values = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = values.pop("hash", "")
    if not received_hash:
        raise HTTPException(status_code=401, detail="Invalid Telegram signature")
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(values.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise HTTPException(status_code=401, detail="Telegram signature check failed")
    try:
        auth_date = int(values.get("auth_date", "0"))
        user = json.loads(values.get("user", "{}"))
        user_id = int(user["id"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Invalid Telegram user")
    if time.time() - auth_date > 86400 or auth_date > time.time() + 60:
        raise HTTPException(status_code=401, detail="Telegram session expired")
    return {"id": user_id, "first_name": str(user.get("first_name", "Admin"))}

async def require_web_admin(init_data: str):
    user = validate_init_data(init_data)
    if not await is_admin(user["id"]):
        raise HTTPException(status_code=403, detail="Admin access denied")
    return user

@app.get("/")
async def root():
    return {"ok": True, "service": "swiggy-swagger-bot"}

@app.get("/health")
async def health():
    return {"ok": True, "service": "swiggy-swagger-bot", "phonepe": "disabled-until-verified"}

@app.get("/admin-app")
async def admin_app():
    page = STATIC_DIR / "index.html"
    if not page.is_file():
        raise HTTPException(status_code=404, detail="Admin app not installed")
    return FileResponse(page)

@app.get("/admin-app/api/dashboard")
async def dashboard(x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    admin = await require_web_admin(x_telegram_init_data)
    try:
        users = await db().fetchval("SELECT COUNT(*) FROM users")
        orders = await db().fetchval("SELECT COUNT(*) FROM orders")
        paid = await db().fetchval("SELECT COUNT(*) FROM orders WHERE status='paid'")
        tickets = await db().fetchval("SELECT COUNT(*) FROM tickets")
        pending = await db().fetchval("SELECT COUNT(*) FROM orders WHERE status IN ('pending','created')")
        support = await db().fetchval("SELECT COUNT(*) FROM support_tickets WHERE status='open'")
        return {"ok": True, "admin": admin["first_name"], "stats": {
            "users": int(users or 0), "orders": int(orders or 0),
            "paid_orders": int(paid or 0), "tickets": int(tickets or 0),
            "pending_orders": int(pending or 0), "open_support": int(support or 0)
        }}
    except HTTPException:
        raise
    except Exception:
        log.exception("Admin Web App dashboard query failed")
        raise HTTPException(status_code=503, detail="Dashboard data temporarily unavailable")

@app.post("/phonepe/callback")
async def phonepe_callback(request):
    raw = (await request.body()).decode("utf-8", errors="replace")
    if not verify_webhook_signature(raw, request.headers.get("X-VERIFY", "")):
        log.warning("Rejected unverified PhonePe callback")
        return Response(status_code=401)
    return Response(status_code=501)


@app.get("/admin-app/api/features")
async def list_shop_features(x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    admin = await require_web_admin(x_telegram_init_data)
    try:
        rows = await db().fetch("SELECT feature_key,is_enabled,updated_by,updated_at FROM shop_feature_flags")
        saved = {r["feature_key"]: r for r in rows}
        master = bool(saved[MASTER_KEY]["is_enabled"]) if MASTER_KEY in saved else False
        result = []
        for item in FEATURES:
            row = saved.get(item["key"])
            enabled = bool(row["is_enabled"]) if row else False
            result.append({**item, "enabled": enabled, "effective": enabled and (master or item["key"] == MASTER_KEY)})
        return {"ok": True, "admin": admin["first_name"], "master_enabled": master, "features": result}
    except Exception:
        log.exception("Feature switch list failed")
        raise HTTPException(status_code=503, detail="Feature settings temporarily unavailable")


@app.post("/admin-app/api/features/{feature_key}")
async def set_shop_feature(feature_key: str, request: Request,
                           x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    admin = await require_web_admin(x_telegram_init_data)
    if feature_key not in FEATURE_KEYS:
        raise HTTPException(status_code=404, detail="Unknown feature")
    try:
        payload = await request.json()
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            raise HTTPException(status_code=422, detail="enabled must be true or false")
        async with db().acquire() as conn:
            async with conn.transaction():
                previous = await conn.fetchval("SELECT is_enabled FROM shop_feature_flags WHERE feature_key=$1 FOR UPDATE", feature_key)
                old_value = bool(previous) if previous is not None else False
                await conn.execute(
                    """INSERT INTO shop_feature_flags(feature_key,is_enabled,updated_by,updated_at)
                       VALUES($1,$2,$3,NOW())
                       ON CONFLICT(feature_key) DO UPDATE
                       SET is_enabled=EXCLUDED.is_enabled,updated_by=EXCLUDED.updated_by,updated_at=NOW()""",
                    feature_key, enabled, admin["id"])
                await conn.execute(
                    """INSERT INTO shop_feature_audit(feature_key,old_value,new_value,changed_by)
                       VALUES($1,$2,$3,$4)""",
                    feature_key, old_value, enabled, admin["id"])
        return {"ok": True, "feature_key": feature_key, "enabled": enabled}
    except HTTPException:
        raise
    except Exception:
        log.exception("Feature switch update failed: %s", feature_key)
        raise HTTPException(status_code=503, detail="Could not save feature setting")


# Digital shop management APIs. These operate only on the dedicated digital_inventory tables.
from feature_service import feature_enabled as _shop_feature_enabled

async def _shop_admin(init_data: str):
    admin = await require_web_admin(init_data)
    return admin

async def _shop_audit(conn, admin_id: int, action: str, details: dict):
    await conn.execute(
        """INSERT INTO admin_audit_log(admin_id,action,details)
           VALUES($1,$2,$3::jsonb)""",
        admin_id, action, json.dumps(details, ensure_ascii=False),
    )

@app.get("/admin-app/api/shop/categories")
async def shop_categories(x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    await _shop_admin(x_telegram_init_data)
    if not await _shop_feature_enabled("products_digital_inventory_product_categories"):
        raise HTTPException(status_code=403, detail="Category management is disabled")
    rows = await db().fetch(
        """SELECT c.id,c.key,c.label,c.price_paise,c.is_active,c.position,
                  COUNT(i.id) FILTER (WHERE i.status='available') AS available_count
           FROM inventory_categories c LEFT JOIN digital_inventory i ON i.category_id=c.id
           GROUP BY c.id ORDER BY c.position,c.id"""
    )
    return {"ok": True, "categories": [dict(row) for row in rows]}

@app.post("/admin-app/api/shop/categories")
async def create_shop_category(request: Request, x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    admin = await _shop_admin(x_telegram_init_data)
    if not await _shop_feature_enabled("products_digital_inventory_product_categories"):
        raise HTTPException(status_code=403, detail="Category management is disabled")
    payload = await request.json()
    key = str(payload.get("key", "")).strip().lower()
    label = str(payload.get("label", "")).strip()
    price = payload.get("price_paise")
    if not key or len(key) > 50 or not key.replace("_", "").isalnum():
        raise HTTPException(status_code=422, detail="Invalid category key")
    if not label or len(label) > 80:
        raise HTTPException(status_code=422, detail="Label must be 1-80 characters")
    if isinstance(price, bool) or not isinstance(price, int) or not 0 <= price <= 100000000:
        raise HTTPException(status_code=422, detail="price_paise must be a valid integer")
    try:
        async with db().acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """INSERT INTO inventory_categories(key,label,price_paise)
                       VALUES($1,$2,$3) RETURNING id,key,label,price_paise,is_active,position""",
                    key,label,price)
                await _shop_audit(conn,admin["id"],"shop_category_created",{"category_id":row["id"],"key":key})
        return {"ok":True,"category":dict(row)}
    except Exception as exc:
        if exc.__class__.__name__ == "UniqueViolationError":
            raise HTTPException(status_code=409, detail="Category key already exists")
        log.exception("Create digital shop category failed")
        raise HTTPException(status_code=503, detail="Could not create category")

@app.patch("/admin-app/api/shop/categories/{category_id}")
async def update_shop_category(category_id: int, request: Request, x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    admin = await _shop_admin(x_telegram_init_data)
    if not await _shop_feature_enabled("products_digital_inventory_category_pricing"):
        raise HTTPException(status_code=403, detail="Category pricing is disabled")
    payload = await request.json()
    label = payload.get("label")
    price = payload.get("price_paise")
    active = payload.get("is_active")
    if label is not None and (not isinstance(label,str) or not label.strip() or len(label.strip()) > 80):
        raise HTTPException(status_code=422, detail="Invalid label")
    if price is not None and (isinstance(price,bool) or not isinstance(price,int) or not 0 <= price <= 100000000):
        raise HTTPException(status_code=422, detail="Invalid price_paise")
    if active is not None and not isinstance(active,bool):
        raise HTTPException(status_code=422, detail="is_active must be boolean")
    if label is None and price is None and active is None:
        raise HTTPException(status_code=422, detail="No changes supplied")
    async with db().acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """UPDATE inventory_categories SET
                   label=COALESCE($2,label),price_paise=COALESCE($3,price_paise),
                   is_active=COALESCE($4,is_active),updated_at=NOW()
                   WHERE id=$1 RETURNING id,key,label,price_paise,is_active,position""",
                category_id,label.strip() if label is not None else None,price,active)
            if not row:
                raise HTTPException(status_code=404,detail="Category not found")
            await _shop_audit(conn,admin["id"],"shop_category_updated",{"category_id":category_id,"changes":payload})
    return {"ok":True,"category":dict(row)}

@app.get("/admin-app/api/shop/products")
async def shop_products(x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data"), limit: int = 100, offset: int = 0):
    await _shop_admin(x_telegram_init_data)
    if not await _shop_feature_enabled("products_digital_inventory_product_catalogue"):
        raise HTTPException(status_code=403,detail="Product catalogue is disabled")
    limit=max(1,min(limit,200)); offset=max(0,offset)
    rows=await db().fetch(
        """SELECT i.id,i.category_id,c.label AS category,i.item_type,i.file_name,i.mime_type,
                  i.file_size,i.caption,i.text_content,i.status,i.added_by,i.created_at
           FROM digital_inventory i JOIN inventory_categories c ON c.id=i.category_id
           ORDER BY i.id DESC LIMIT $1 OFFSET $2""",limit,offset)
    return {"ok":True,"products":[dict(row) for row in rows],"limit":limit,"offset":offset}

@app.post("/admin-app/api/shop/products")
async def create_shop_product(request: Request, x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    admin=await _shop_admin(x_telegram_init_data)
    payload=await request.json()
    item_type=payload.get("item_type")
    category_id=payload.get("category_id")
    file_id=payload.get("telegram_file_id")
    text_content=payload.get("text_content")
    if item_type not in {"document","photo","text"}:
        raise HTTPException(status_code=422,detail="item_type must be document, photo or text")
    if isinstance(category_id,bool) or not isinstance(category_id,int):
        raise HTTPException(status_code=422,detail="category_id must be an integer")
    if item_type=="text":
        if not await _shop_feature_enabled("products_digital_inventory_text_product_editor"):
            raise HTTPException(status_code=403,detail="Text product editor is disabled")
        if not isinstance(text_content,str) or not text_content.strip() or len(text_content)>10000:
            raise HTTPException(status_code=422,detail="Text content must be 1-10000 characters")
    else:
        if not await _shop_feature_enabled("products_digital_inventory_digital_file_upload"):
            raise HTTPException(status_code=403,detail="Digital file upload is disabled")
        if not isinstance(file_id,str) or not file_id.strip():
            raise HTTPException(status_code=422,detail="Telegram file_id is required")
    if not await _shop_feature_enabled("products_digital_inventory_add_digital_product"):
        raise HTTPException(status_code=403,detail="Add product is disabled")
    try:
        async with db().acquire() as conn:
            async with conn.transaction():
                category=await conn.fetchrow("SELECT id FROM inventory_categories WHERE id=$1 AND is_active=TRUE FOR SHARE",category_id)
                if not category:
                    raise HTTPException(status_code=404,detail="Active category not found")
                row=await conn.fetchrow(
                    """INSERT INTO digital_inventory(category_id,item_type,telegram_file_id,file_name,mime_type,
                       file_size,caption,text_content,added_by)
                       VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)
                       RETURNING id,category_id,item_type,file_name,status,created_at""",
                    category_id,item_type,file_id,payload.get("file_name"),payload.get("mime_type"),
                    payload.get("file_size"),payload.get("caption"),text_content,admin["id"])
                await _shop_audit(conn,admin["id"],"shop_product_created",{"product_id":row["id"],"category_id":category_id,"item_type":item_type})
        return {"ok":True,"product":dict(row)}
    except HTTPException:
        raise
    except Exception:
        log.exception("Create digital product failed")
        raise HTTPException(status_code=503,detail="Could not create digital product")

@app.patch("/admin-app/api/shop/products/{product_id}")
async def update_shop_product(product_id: int, request: Request, x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    admin=await _shop_admin(x_telegram_init_data)
    if not await _shop_feature_enabled("products_digital_inventory_edit_product"):
        raise HTTPException(status_code=403,detail="Edit product is disabled")
    payload=await request.json()
    status=payload.get("status")
    caption=payload.get("caption")
    if status is not None and status not in {"available","disabled"}:
        raise HTTPException(status_code=422,detail="status must be available or disabled")
    if caption is not None and (not isinstance(caption,str) or len(caption)>1000):
        raise HTTPException(status_code=422,detail="caption must be at most 1000 characters")
    if status is None and caption is None:
        raise HTTPException(status_code=422,detail="No changes supplied")
    async with db().acquire() as conn:
        async with conn.transaction():
            row=await conn.fetchrow(
                """UPDATE digital_inventory SET status=COALESCE($2,status),caption=COALESCE($3,caption)
                   WHERE id=$1 AND status <> 'sold'
                   RETURNING id,category_id,item_type,file_name,status,caption""",
                product_id,status,caption)
            if not row:
                raise HTTPException(status_code=404,detail="Product not found or already sold")
            await _shop_audit(conn,admin["id"],"shop_product_updated",{"product_id":product_id,"changes":payload})
    return {"ok":True,"product":dict(row)}

@app.post("/admin-app/api/shop/products/{product_id}/disable")
async def disable_shop_product(product_id: int, x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    admin=await _shop_admin(x_telegram_init_data)
    if not await _shop_feature_enabled("products_digital_inventory_delete_product_soft_disable"):
        raise HTTPException(status_code=403,detail="Product soft-disable is disabled")
    async with db().acquire() as conn:
        async with conn.transaction():
            row=await conn.fetchrow(
                "UPDATE digital_inventory SET status='disabled' WHERE id=$1 AND status='available' RETURNING id",
                product_id)
            if not row:
                raise HTTPException(status_code=404,detail="Available product not found")
            await _shop_audit(conn,admin["id"],"shop_product_soft_disabled",{"product_id":product_id})
    return {"ok":True,"product_id":product_id,"status":"disabled"}


# Read-only operational views for the digital shop admin dashboard.
@app.get("/admin-app/api/shop/orders")
async def shop_orders(x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data"), limit: int = 50, offset: int = 0, status: str = ""):
    await _shop_admin(x_telegram_init_data)
    if not await _shop_feature_enabled("orders_delivery_all_orders"):
        raise HTTPException(status_code=403, detail="Order management is disabled")
    limit=max(1,min(limit,100)); offset=max(0,offset)
    allowed={"pending","processing","paid","failed","cancelled","refunded"}
    if status and status not in allowed:
        raise HTTPException(status_code=422,detail="Invalid order status")
    rows=await db().fetch(
        """SELECT o.order_id::text,o.user_id,o.amount,o.currency,o.status,o.gateway,
                  o.created_at,o.paid_at,u.username,u.first_name
           FROM orders o JOIN users u ON u.telegram_id=o.user_id
           WHERE ($1='' OR o.status=$1)
           ORDER BY o.created_at DESC LIMIT $2 OFFSET $3""",status,limit,offset)
    return {"ok":True,"orders":[dict(r) for r in rows],"limit":limit,"offset":offset}

@app.get("/admin-app/api/shop/customers")
async def shop_customers(x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data"), limit: int = 50, offset: int = 0, q: str = ""):
    await _shop_admin(x_telegram_init_data)
    if not await _shop_feature_enabled("customers_users_customer_directory"):
        raise HTTPException(status_code=403,detail="Customer directory is disabled")
    limit=max(1,min(limit,100)); offset=max(0,offset); q=q.strip()[:80]
    rows=await db().fetch(
        """SELECT u.telegram_id,u.username,u.first_name,u.full_name,u.created_at,
                  COALESCE(w.balance_paise,0) AS wallet_balance_paise,
                  (SELECT COUNT(*) FROM orders o WHERE o.user_id=u.telegram_id) AS order_count
           FROM users u LEFT JOIN wallets w ON w.user_id=u.telegram_id
           WHERE ($1='' OR u.telegram_id::text ILIKE '%'||$1||'%' OR COALESCE(u.username,'') ILIKE '%'||$1||'%' OR COALESCE(u.full_name,u.first_name,'') ILIKE '%'||$1||'%')
           ORDER BY u.created_at DESC LIMIT $2 OFFSET $3""",q,limit,offset)
    return {"ok":True,"customers":[dict(r) for r in rows],"limit":limit,"offset":offset}

@app.get("/admin-app/api/shop/support")
async def shop_support(x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data"), limit: int = 50, offset: int = 0, status: str = "open"):
    await _shop_admin(x_telegram_init_data)
    if not await _shop_feature_enabled("support_notifications_support_inbox"):
        raise HTTPException(status_code=403,detail="Support inbox is disabled")
    if status not in {"open","closed","all"}:
        raise HTTPException(status_code=422,detail="Invalid support status")
    limit=max(1,min(limit,100)); offset=max(0,offset)
    rows=await db().fetch(
        """SELECT id,user_id,username,full_name,COALESCE(message,query,'') AS message,
                  status,admin_reply,created_at,replied_at
           FROM support_tickets WHERE ($1='all' OR status=$1)
           ORDER BY created_at DESC LIMIT $2 OFFSET $3""",status,limit,offset)
    return {"ok":True,"tickets":[dict(r) for r in rows],"limit":limit,"offset":offset}
