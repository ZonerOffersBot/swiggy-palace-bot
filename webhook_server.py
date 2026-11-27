import logging

from fastapi import FastAPI
from fastapi.responses import Response

from config import BOT_TOKEN
from services_phonepe import verify_webhook_signature

log = logging.getLogger(__name__)
app = FastAPI()

@app.post("/phonepe/callback")
async def phonepe_callback(request):
    raw = (await request.body()).decode("utf-8", errors="replace")
    if not verify_webhook_signature(raw, request.headers.get("X-VERIFY", "")):
        log.warning("Rejected unverified PhonePe callback")
        return Response(status_code=401)
    return Response(status_code=501)
