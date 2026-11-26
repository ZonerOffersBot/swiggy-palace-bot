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
