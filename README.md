# Dino Wallet Service

A simple wallet service for managing in-app credits with strong data integrity guarantees.

## Quickstart (Local)

1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt`
3. `export DATABASE_URL=sqlite:///./wallet.db` (optional)
4. `uvicorn main:app --reload`
5. `./setup.sh` or `python seed.py`

## Docker

### Dev (reload + bind mount)

1. `docker compose up --build`
2. `docker compose exec web ./setup.sh`

### Prod-like (no reload)

1. `docker compose -f docker-compose.prod.yml up --build`
2. `docker compose -f docker-compose.prod.yml exec web ./setup.sh`

## Railway

- Set `DATABASE_URL` to the Railway Postgres connection string.
- Railway injects `PORT` automatically; the Dockerfile uses it.
- Optional: set `WEB_CONCURRENCY` to control Uvicorn workers.

## API

- `POST /transact` (requires `Idempotency-Key` header and `asset_code` in body)
- `GET /balance/{user_id}?asset_code=GOLD_COIN`
- `GET /transactions/{user_id}?asset_code=GOLD_COIN`

## Technology Choice

- FastAPI + SQLModel for a minimal, type-safe REST service
- PostgreSQL (via Docker) for ACID transactions and row-level locks
- SQLite for local development convenience

## Concurrency and Integrity Strategy

- All balance changes happen within a single database transaction.
- Row-level locks (`SELECT ... FOR UPDATE`) are acquired in deterministic order to avoid deadlocks.
- Idempotency is scoped to `user_id` and request payload hash; key reuse with different payload returns `409`.
- A double-entry ledger (`LedgerEntry`) records every credit and debit for auditability.

## Notes

- This sample supports multiple asset types per user by scoping wallets to `(user_id, asset_type_id)`.
- For local SQLite dev, `check_same_thread=False` is enabled; for concurrency testing use Postgres via Docker.
