# Event Ticket Telegram Bot

This development branch contains the event-ticket rewrite, using aiogram, PostgreSQL, Telegram Stars invoices, PDF ticket delivery, an admin check-in command, and a health endpoint.

## Setup
1. Set environment variables from `.env.example` in your host (never commit real credentials).
2. Provision PostgreSQL and set `DATABASE_URL`.
3. Install dependencies from `requirements.txt`.
4. Run `python main.py`.

## Payment safety
Telegram Stars payments are validated against the stored order, Telegram user, currency and amount. PhonePe is deliberately disabled until the merchant-specific current API, callback authentication and status verification are implemented and tested. Never treat a redirect or screenshot as payment confirmation.

## Deployment warning
This is a development rewrite. Test with a test bot and sandbox database before deploying. Existing PostgreSQL schemas need explicit migrations; `CREATE TABLE IF NOT EXISTS` does not migrate old tables.
