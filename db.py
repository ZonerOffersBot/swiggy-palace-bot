from pathlib import Path
import asyncpg
from config import DATABASE_URL

_pool = None

async def init_db():
    global _pool
    if _pool is not None: return
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10, command_timeout=30)
    schema = (Path(__file__).resolve().parent / "schema.sql").read_text(encoding="utf-8")
    async with _pool.acquire() as conn:
        await conn.execute(schema)

def db():
    if _pool is None: raise RuntimeError("Database is not initialized")
    return _pool

async def close_db():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
