"""PhonePe integration deliberately fails closed until the merchant-specific API contract is configured and verified.
Do not mark an order paid from a browser redirect or an unverified callback.
"""
class PhonePeError(RuntimeError):
    pass

async def create_checkout(*args, **kwargs):
    raise PhonePeError("PhonePe checkout is disabled until the merchant's current OAuth/checkout API and callback verification are implemented and tested.")

async def check_payment_status(*args, **kwargs):
    raise PhonePeError("PhonePe status API is not configured.")

def verify_webhook_signature(raw_body: str, signature: str) -> bool:
    # Fail closed; legacy X-VERIFY formulas must not be assumed for current OAuth APIs.
    return False
