import logging
from fastapi import FastAPI, Request, Response
from services_phonepe import verify_webhook_signature
log=logging.getLogger(__name__)
app=FastAPI()

@app.get("/")
async def root():
    # Render may probe the root URL; return a lightweight health response instead of 404.
    return {"ok": True, "service": "swiggy-swagger-bot"}

@app.get("/health")
async def health():
    return {"ok": True, "service": "swiggy-swagger-bot", "phonepe": "disabled-until-verified"}

@app.post("/phonepe/callback")
async def phonepe_callback(request: Request):
    raw=(await request.body()).decode("utf-8",errors="replace")
    if not verify_webhook_signature(raw,request.headers.get("X-VERIFY","")):
        log.warning("Rejected unverified PhonePe callback")
        return Response(status_code=401)
    # Deliberately no payment mutation until the current merchant callback schema and signature are verified.
    return Response(status_code=501)
