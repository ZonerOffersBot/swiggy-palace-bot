# Swiggy Palace — Java stability migration

This branch introduces a Java 21 + Spring Boot implementation focused on stable Telegram delivery.

## Why this version is different

- Render uses Docker because Render does not provide a native JVM runtime.
- Telegram uses **webhook mode**, so the bot does not run competing getUpdates pollers.
- Every Telegram update is acknowledged immediately and processed by an isolated worker.
- Duplicate update IDs are guarded in SQLite.
- SQLite uses WAL and a busy timeout.
- Global callback/update exception handling prevents one bad interaction from taking down the service.
- / and /health are always available for Render health checks.
- Existing database table names are retained where practical.

## Environment

BOT_TOKEN, OWNER_ID, ADMIN_IDS, DATABASE_PATH, PORT, and optional WEBHOOK_URL.

Do not run the old Python bot with the same token while this Java webhook deployment is active.

## Migration note

The stable transport/admin foundation is implemented first. The remaining Python business workflows should be ported module-by-module before switching the production service permanently.
