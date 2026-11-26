"""Runtime feature gates for the digital shop. Disabled or unreadable flags fail closed."""
import logging
from db import db
from feature_controls import MASTER_KEY, FEATURE_KEYS

log = logging.getLogger(__name__)

async def feature_enabled(key: str) -> bool:
    if key not in FEATURE_KEYS:
        return False
    try:
        values = await db().fetch(
            "SELECT feature_key,is_enabled FROM shop_feature_flags WHERE feature_key = ANY($1::text[])",
            [MASTER_KEY, key],
        )
        flags = {row["feature_key"]: bool(row["is_enabled"]) for row in values}
        if key == MASTER_KEY:
            return flags.get(MASTER_KEY, False)
        return flags.get(MASTER_KEY, False) and flags.get(key, False)
    except Exception:
        log.exception("Feature gate lookup failed for %s; denying access", key)
        return False
