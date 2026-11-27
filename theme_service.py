from db import db

async def screen_photo(key: str, fallback):
    try:
        value = await db().fetchval("SELECT value FROM bot_settings WHERE key=$1", key)
        return value or fallback
    except Exception:
        return fallback
