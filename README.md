# 🦕 Dino Wallet Service

A production-grade internal wallet microservice for managing virtual in-app credits on high-traffic platforms like gaming or loyalty reward systems. Built with FastAPI, SQLModel, and PostgreSQL — featuring double-entry bookkeeping, row-level locking, idempotent transactions, and full Docker support.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Technology Stack & Rationale](#technology-stack--rationale)
- [Project Structure](#project-structure)
- [Data Models](#data-models)
- [API Reference](#api-reference)
- [Concurrency & Integrity Strategy](#concurrency--integrity-strategy)
- [Idempotency](#idempotency)
- [Double-Entry Ledger](#double-entry-ledger)
- [Quickstart — Local (SQLite)](#quickstart--local-sqlite)
- [Quickstart — Local with Docker (PostgreSQL)](#quickstart--local-with-docker-postgresql)
- [Production Docker](#production-docker)
- [Deploying to Railway](#deploying-to-railway)
- [Environment Variables](#environment-variables)
- [Database Seeding](#database-seeding)
- [Testing with Postman](#testing-with-postman)
- [Known Limitations & Future Improvements](#known-limitations--future-improvements)

---

## Overview

This service is a **closed-loop** wallet system — virtual credits (Gold Coins, Diamonds, Loyalty Points, etc.) exist only within the application. They are not real money, not crypto, and cannot be transferred between users. Despite the virtual nature of the currency, **data integrity is treated as if it were real money**: every credit and debit is recorded with full auditability, balances never go negative, and no transaction can be lost under concurrent load or system failure.

### Core Capabilities

- **Wallet Top-up (TOPUP):** Credits a user wallet when they purchase in-app currency with real money. Assumes a fully functional upstream payment system has already processed the payment.
- **Bonus/Incentive (BONUS):** Grants free credits to a user (referral bonuses, promotions, game rewards). Funded from the system treasury.
- **Spend (SPEND):** Debits a user's wallet when they redeem credits for an in-app item or service.

All three flows are handled as atomic database transactions with row-level locking, preventing any race condition from corrupting balances.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI Application                       │
│                                                                  │
│  POST /transact   GET /balance/{id}   GET /transactions/{id}    │
│        │                  │                      │               │
│        ▼                  ▼                      ▼               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Business Logic Layer                    │   │
│  │  • Idempotency check (early return if replay)             │   │
│  │  • Asset normalization (lowercase → uppercase)            │   │
│  │  • Row lock acquisition (ascending ID order)              │   │
│  │  • Balance validation (no negative balances)              │   │
│  │  • Double-entry ledger write                              │   │
│  │  • Idempotency record write                               │   │
│  └──────────────────────────────────────────────────────────┘   │
│        │                                                         │
│        ▼                                                         │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    SQLModel / SQLAlchemy                   │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
              ┌──────────────────────────┐
              │   PostgreSQL (or SQLite)  │
              │                          │
              │  AssetType               │
              │  Wallet (user + system)  │
              │  LedgerEntry             │
              │  Idempotency             │
              └──────────────────────────┘
```

### Double-Entry Flow (TOPUP example)

```
User purchases 100 GOLD_COIN

  SYSTEM_TREASURY wallet      user_123 wallet
  ┌─────────────────┐         ┌─────────────────┐
  │ balance: 1000000│  ─100→  │ balance: 100    │
  │ balance: 999900 │         │ balance: 200    │
  └─────────────────┘         └─────────────────┘
         │                           │
         └───────┬───────────────────┘
                 ▼
        LedgerEntry (tx_id=abc)
        wallet_id=system, amount=-100, reason=TOPUP
        LedgerEntry (tx_id=abc)
        wallet_id=user,   amount=+100, reason=TOPUP
```

---

## Technology Stack & Rationale

| Component | Choice | Why |
|---|---|---|
| **Language** | Python 3.11 | Fast iteration, excellent async ecosystem, strong typing with Pydantic |
| **Web Framework** | FastAPI | Automatic OpenAPI docs, Pydantic validation, async-ready, minimal boilerplate |
| **ORM / Models** | SQLModel | Unifies Pydantic models and SQLAlchemy table definitions — single source of truth for schema and validation |
| **Database (prod)** | PostgreSQL 15 | ACID transactions, row-level locking (`SELECT FOR UPDATE`), mature concurrency primitives — essential for financial integrity |
| **Database (dev)** | SQLite | Zero setup for local development; sufficient for functional testing (note: `FOR UPDATE` is silently ignored by SQLite — use Docker for concurrency testing) |
| **Server** | Uvicorn + Gunicorn workers | Production ASGI server; `WEB_CONCURRENCY` env var controls worker count |
| **Containerization** | Docker + Docker Compose | Reproducible environment; dev compose includes hot reload, prod compose runs multiple workers |

---

## Project Structure

```
.
├── main.py                  # FastAPI app, all endpoints, transaction logic
├── models.py                # SQLModel table definitions (Wallet, LedgerEntry, Idempotency, AssetType)
├── database.py              # Engine creation, session factory, init_db()
├── seed.py                  # Idempotent database seeding script
├── setup.sh                 # Thin shell wrapper that calls seed.py
├── requirements.txt         # Python dependencies (pinned versions)
├── Dockerfile               # Multi-purpose image for dev and prod
├── docker-compose.yml       # Dev: hot reload, bind mount, single worker
├── docker-compose.prod.yml  # Prod-like: no reload, multiple workers
└── README.md                # This file
```

---

## Data Models

### AssetType

Defines a type of virtual currency available in the system.

| Column | Type | Description |
|---|---|---|
| `id` | Integer PK | Auto-increment primary key |
| `code` | String (unique, indexed) | Canonical identifier e.g. `GOLD_COIN` |
| `name` | String | Human-readable label e.g. `Gold Coins` |
| `created_at` | DateTime | UTC timestamp at creation |

### Wallet

One wallet record per `(user_id, asset_type_id)` pair. Both real users and the `SYSTEM_TREASURY` have wallet records.

| Column | Type | Description |
|---|---|---|
| `id` | Integer PK | Auto-increment primary key — used for lock ordering |
| `user_id` | String (indexed) | User identifier or `SYSTEM_TREASURY` |
| `balance` | Integer | Current balance in the smallest unit of the asset |
| `asset_type_id` | Integer FK | Foreign key to `AssetType.id` |
| `created_at` | DateTime | UTC timestamp at creation |

**Constraint:** `UNIQUE(user_id, asset_type_id)` — one wallet per user per asset.

### LedgerEntry

Immutable audit log. Every transaction produces exactly two entries (user wallet + system wallet).

| Column | Type | Description |
|---|---|---|
| `id` | Integer PK | Auto-increment primary key |
| `transaction_id` | String (indexed) | UUID shared between the two paired entries |
| `wallet_id` | Integer FK | Foreign key to `Wallet.id` |
| `amount` | Integer | Positive = credit, Negative = debit |
| `reason` | String | Transaction type: `TOPUP`, `BONUS`, or `SPEND` |
| `created_at` | DateTime | UTC timestamp |

### Idempotency

Prevents duplicate transaction processing on retried requests.

| Column | Type | Description |
|---|---|---|
| `key` | String (PK) | Client-supplied idempotency key |
| `user_id` | String (PK) | Scopes the key to a specific user; composite PK with `key` |
| `request_hash` | String | SHA-256 of the request payload |
| `response_payload` | String | JSON-serialized response body for replaying |
| `created_at` | DateTime | UTC timestamp |

---

## API Reference

### `GET /health`

Returns service health status. No authentication required.

**Response 200:**
```json
{ "status": "ok" }
```

---

### `GET /balance/{user_id}?asset_code=GOLD_COIN`

Returns the current balance for a user and asset pair.

**Path Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `user_id` | string | The user's identifier |

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `asset_code` | string | ✅ | Asset code e.g. `GOLD_COIN` (case-insensitive, normalized to uppercase) |

**Response 200:**
```json
{
  "user_id": "user_123",
  "balance": 150,
  "asset_type_id": 1,
  "asset_code": "GOLD_COIN"
}
```

**Error Responses:**

| Code | Reason |
|---|---|
| 404 | Asset type not found, or no wallet exists for this user/asset pair |
| 422 | `asset_code` missing or blank |

---

### `GET /transactions/{user_id}?asset_code=GOLD_COIN`

Returns full transaction history for a user and asset, ordered newest-first.

**Path Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `user_id` | string | The user's identifier |

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `asset_code` | string | ✅ | Asset code (case-insensitive) |

**Response 200:**
```json
{
  "user_id": "user_123",
  "asset_code": "GOLD_COIN",
  "asset_type_id": 1,
  "current_balance": 150,
  "transactions": [
    {
      "transaction_id": "550e8400-e29b-41d4-a716-446655440000",
      "amount": 50,
      "type": "TOPUP",
      "created_at": "2024-01-15T10:30:00"
    }
  ]
}
```

**Error Responses:**

| Code | Reason |
|---|---|
| 404 | Asset type not found, or no wallet exists for this user/asset pair |
| 422 | `asset_code` missing or blank |

---

### `POST /transact`

Executes a wallet transaction. This is the core endpoint.

**Required Headers:**

| Header | Type | Description |
|---|---|---|
| `Idempotency-Key` | string | Unique key for this request. Any format is accepted (UUID recommended). Scoped per user — the same key can be reused by different users. |

**Request Body:**
```json
{
  "user_id": "user_123",
  "amount": 100,
  "transaction_type": "TOPUP",
  "asset_code": "GOLD_COIN"
}
```

| Field | Type | Constraints | Description |
|---|---|---|---|
| `user_id` | string | Required, not `SYSTEM_TREASURY` | The user to transact on |
| `amount` | integer | Required, `> 0` | Amount in the smallest unit of the asset |
| `transaction_type` | enum | `TOPUP`, `BONUS`, or `SPEND` | Direction and reason for the transaction |
| `asset_code` | string | Required, min length 1 | Asset code (case-insensitive) |

**Transaction Type Semantics:**

| Type | User Wallet | System Treasury | When to Use |
|---|---|---|---|
| `TOPUP` | +amount (credit) | -amount (debit) | User purchased credits with real money |
| `BONUS` | +amount (credit) | -amount (debit) | System granted free credits (referral, promo) |
| `SPEND` | -amount (debit) | +amount (credit) | User spent credits on an in-app item |

**Response 200:**
```json
{
  "tx_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "user_123",
  "transaction_type": "TOPUP",
  "amount": 100,
  "new_balance": 200,
  "asset_type_id": 1,
  "asset_code": "GOLD_COIN"
}
```

**Error Responses:**

| Code | Reason |
|---|---|
| 400 | Missing `Idempotency-Key` header |
| 400 | `user_id` is `SYSTEM_TREASURY` (reserved) |
| 400 | Insufficient funds (SPEND amount exceeds balance) |
| 404 | Asset type not found |
| 404 | No wallet found for user/asset pair (run seeding first) |
| 409 | `Idempotency-Key` already used with a different request payload |
| 422 | Validation error (amount ≤ 0, missing fields, blank asset_code) |

**Idempotency Replay:** If you send the exact same request again with the same `Idempotency-Key`, the service returns the original cached response immediately — no second transaction is recorded.

---

## Concurrency & Integrity Strategy

This section describes the mechanisms that keep data correct under heavy concurrent load.

### Row-Level Locking with Consistent Ordering

Every `/transact` call modifies two wallet rows: the user's wallet and `SYSTEM_TREASURY`. Without careful ordering, two concurrent transactions could each lock the first wallet and then wait for the other's lock — a classic **deadlock**.

The service avoids this by always acquiring locks in **ascending wallet `id` order**, regardless of which wallet belongs to the user or the system:

```python
lock_first_id  = min(user_wallet.id, system_wallet.id)
lock_second_id = max(user_wallet.id, system_wallet.id)

session.exec(select(Wallet).where(Wallet.id == lock_first_id).with_for_update()).first()
session.exec(select(Wallet).where(Wallet.id == lock_second_id).with_for_update()).first()
```

Because every concurrent request locks in the same global order, cyclic-wait is structurally impossible. After acquiring both locks, wallets are re-fetched to get the latest state before computing balances.

> ⚠️ **SQLite note:** `SELECT FOR UPDATE` is silently ignored by SQLite. The locking strategy only functions correctly with PostgreSQL. Use Docker for any concurrency testing.

### Balance Check After Locking

The insufficient-funds check happens **after** row locks are acquired, not before. This closes the classic TOCTOU (Time-of-Check/Time-of-Use) race condition where two concurrent SPEND requests both read a sufficient balance, both pass the check, and one ends up overdrafting the wallet.

### Atomic Transactions

Both `LedgerEntry` inserts, both `Wallet` balance updates, and the `Idempotency` record write all occur within a single database transaction. Either all six writes commit together, or all six roll back. No partial state is ever persisted.

---

## Idempotency

Network retries are unavoidable. Without idempotency, a client that retries a timed-out request risks double-charging a user. The service handles this at the database level.

### How It Works

1. The client provides a unique `Idempotency-Key` header with every `/transact` request.
2. Before processing, the service checks if this `(key, user_id)` pair already exists in the `Idempotency` table.
3. If found and the request hash matches → return the stored response immediately. No DB write. No second transaction.
4. If found but the hash differs → return `409 Conflict`. The key was already used for a different operation.
5. If not found → process normally, then store the response in the `Idempotency` table as part of the same atomic commit.

### Request Hash

The hash is a SHA-256 of the canonically serialized request fields (`user_id`, `amount`, `transaction_type`, `asset_code`). This ensures that two different payloads can't be replayed through the same key:

```python
payload = {
    "user_id": user_id,
    "amount": amount,
    "transaction_type": transaction_type.value,
    "asset_code": asset_code,
}
hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
```

### Race Condition Fallback

Two concurrent requests with the same key could both pass the initial idempotency check (neither has committed yet). The `Idempotency` table has a composite primary key on `(key, user_id)`, so only one INSERT will succeed — the other will raise `IntegrityError`. The losing request catches this, rolls back, and re-reads the winning request's stored response:

```python
except IntegrityError:
    session.rollback()
    existing = session.exec(select(Idempotency).where(...)).first()
    if existing:
        return json.loads(existing.response_payload)
    raise
```

### Key Scoping

Idempotency keys are scoped to `(key, user_id)`. The same key string used by different users is treated as independent. Clients are responsible for generating globally unique keys per operation — UUIDs (v4) are recommended.

---

## Double-Entry Ledger

Every balance mutation produces exactly two `LedgerEntry` rows sharing a single `transaction_id` (UUID). The sum of all entries for any wallet at any point in time should equal the wallet's current `balance` column — the balance is a denormalized read cache for performance.

```
transaction_id: 550e8400-...

  wallet_id=1 (SYSTEM_TREASURY)   amount=-100   reason=TOPUP
  wallet_id=2 (user_123)          amount=+100   reason=TOPUP
```

This provides:
- **Auditability:** Full history of every credit and debit ever issued
- **Reconciliation:** Any discrepancy between the `balance` column and the sum of ledger entries indicates a data integrity bug
- **Non-repudiation:** Entries are insert-only; nothing is ever deleted or updated

---

## Quickstart — Local (SQLite)

For quick functional development without Docker. No concurrency guarantees.

```bash
# 1. Clone the repository
git clone <repo-url>
cd dino-wallet

# 2. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\Scripts\activate        # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. (Optional) Use SQLite instead of PostgreSQL
export DATABASE_URL=sqlite:///./wallet.db

# 5. Start the server
uvicorn main:app --reload

# 6. Seed the database (in a second terminal)
python seed.py
```

The API is now available at `http://localhost:8000`.
OpenAPI documentation is at `http://localhost:8000/docs`.
ReDoc documentation is at `http://localhost:8000/redoc`.

---

## Quickstart — Local with Docker (PostgreSQL)

Full local environment with PostgreSQL, hot reload, and a bind mount so code changes reflect immediately.

```bash
# 1. Build and start all services (web + postgres)
docker compose up --build

# 2. In a second terminal, seed the database
docker compose exec web ./setup.sh

# 3. Verify
curl http://localhost:8000/health
curl "http://localhost:8000/balance/user_123?asset_code=GOLD_COIN"
```

To stop and remove containers (data is preserved in the Docker volume):
```bash
docker compose down
```

To also wipe the database volume:
```bash
docker compose down -v
```

To re-seed after a wipe:
```bash
docker compose exec web python seed.py
```

---

## Production Docker

Runs with multiple Uvicorn workers, no bind mount, no hot reload.

```bash
# Start
docker compose -f docker-compose.prod.yml up --build -d

# Seed
docker compose -f docker-compose.prod.yml exec web ./setup.sh

# View logs
docker compose -f docker-compose.prod.yml logs -f web

# Stop
docker compose -f docker-compose.prod.yml down
```

---

## Deploying to Railway

Railway is the recommended cloud deployment target. It provides managed PostgreSQL, automatic `DATABASE_URL` injection, and Docker-based deployments with zero additional configuration.

### One-Time Setup

**Step 1 — Apply the two required code fixes before pushing:**

In `database.py`, add the URL prefix fix immediately after reading the env var:
```python
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./wallet.db")
DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
```
Railway injects `postgres://` prefix; SQLAlchemy requires `postgresql://`. Without this fix you will get a cryptic connection error on startup.

In `Dockerfile`, update the `CMD` to auto-seed on startup:
```dockerfile
CMD ["sh", "-c", "python seed.py && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2}"]
```
`seed.py` is fully idempotent and safe to run on every deploy — it skips rows that already exist.

**Step 2 — Push your code to GitHub.**

**Step 3 — Create Railway project:**
1. Go to [railway.com](https://railway.com) → `New Project` → `Deploy from GitHub repo`
2. Select your repository
3. Railway detects the `Dockerfile` and begins building automatically

**Step 4 — Add PostgreSQL:**
1. Inside your Railway project, click `+ New` → `Database` → `Add PostgreSQL`
2. Railway provisions a managed Postgres 15 instance
3. `DATABASE_URL` is automatically injected as an environment variable into your web service — you do not need to configure this manually

**Step 5 — Generate a public domain:**
1. Click on your web service → `Settings` → `Networking` → `Generate Domain`
2. You'll receive a URL like `https://dino-wallet-production.up.railway.app`

**Step 6 — Verify deployment:**
```bash
curl https://your-app.up.railway.app/health
curl "https://your-app.up.railway.app/balance/user_123?asset_code=GOLD_COIN"
```

### Railway Environment Variables

Railway injects `DATABASE_URL` automatically. You can optionally set these in the Railway dashboard under your service's `Variables` tab:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | Auto-injected by Railway | PostgreSQL connection string |
| `PORT` | Auto-injected by Railway | Port for Uvicorn to bind |
| `WEB_CONCURRENCY` | `2` | Number of Uvicorn worker processes |

### Re-seeding on Railway

If you ever need to wipe and re-seed:
1. Go to your PostgreSQL service in the Railway dashboard
2. Connect via the Railway shell or an external client (credentials are in the service's `Connect` tab)
3. Drop and recreate the tables, or use Railway's one-off command runner to execute `python seed.py`

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | No | `sqlite:///./wallet.db` | Full database connection URL |
| `PORT` | No | `8000` | Port the server listens on |
| `WEB_CONCURRENCY` | No | `2` | Number of Uvicorn worker processes |

**`DATABASE_URL` formats:**

```bash
# SQLite (local dev, no concurrency guarantees)
DATABASE_URL=sqlite:///./wallet.db

# PostgreSQL (Docker or hosted)
DATABASE_URL=postgresql://user:password@localhost:5432/wallet_db

# Railway auto-injects this format (requires the postgres:// → postgresql:// fix)
DATABASE_URL=postgresql://postgres:xyz@containers-us-west.railway.app:6543/railway
```

---

## Database Seeding

The seed script (`seed.py`) is **idempotent** — it checks for existing records before inserting and can be run any number of times safely.

### What Gets Seeded

**Asset Types:**

| Code | Name |
|---|---|
| `GOLD_COIN` | Gold Coins |
| `DIAMOND` | Diamonds |
| `LOYALTY_POINT` | Loyalty Points |

**System Wallets (SYSTEM_TREASURY):**

| Asset | Initial Balance |
|---|---|
| `GOLD_COIN` | 1,000,000 |
| `DIAMOND` | 100,000 |
| `LOYALTY_POINT` | 10,000,000 |

**User Wallets:**

| User | Asset | Initial Balance |
|---|---|---|
| `user_123` | `GOLD_COIN` | 100 |
| `user_123` | `DIAMOND` | 10 |
| `user_123` | `LOYALTY_POINT` | 500 |
| `user_456` | `GOLD_COIN` | 50 |
| `user_456` | `DIAMOND` | 5 |

### Running the Seed

```bash
# Directly
python seed.py

# Via shell wrapper
./setup.sh

# Via Docker (dev)
docker compose exec web python seed.py

# Via Docker (prod)
docker compose -f docker-compose.prod.yml exec web python seed.py
```

---

## Testing with Postman

### Setup

1. Import or manually create a Postman Collection named `Dino Wallet Service`.
2. Create a Postman Environment with these variables:

| Variable | Initial Value | Description |
|---|---|---|
| `base_url` | `http://localhost:8000` | Change to Railway URL for cloud testing |
| `idem_key` | _(leave blank)_ | Auto-generated per request via pre-request script |

3. Add this **pre-request script** to the Collection level so every request gets a fresh idempotency key automatically:
```javascript
pm.environment.set("idem_key", pm.variables.replaceIn('{{$guid}}'));
```

4. Add this **Idempotency-Key header** to the Collection level:

| Header | Value |
|---|---|
| `Idempotency-Key` | `{{idem_key}}` |

---

### Folder 1: Health

**GET `{{base_url}}/health`**

Test script:
```javascript
pm.test("Status 200", () => pm.response.to.have.status(200));
pm.test("Status ok", () => pm.expect(pm.response.json().status).to.equal("ok"));
```

---

### Folder 2: Balance — Happy Paths

| Name | Request | Expected |
|---|---|---|
| Balance user_123 GOLD_COIN | `GET /balance/user_123?asset_code=GOLD_COIN` | 200, balance ≥ 0 |
| Balance user_123 DIAMOND | `GET /balance/user_123?asset_code=DIAMOND` | 200 |
| Balance user_456 GOLD_COIN | `GET /balance/user_456?asset_code=GOLD_COIN` | 200 |
| Lowercase asset_code | `GET /balance/user_123?asset_code=gold_coin` | 200 (normalized to uppercase) |
| System treasury | `GET /balance/SYSTEM_TREASURY?asset_code=GOLD_COIN` | 200, large balance |

### Folder 3: Balance — Error Cases

| Name | Request | Expected |
|---|---|---|
| Unknown user | `GET /balance/ghost_user?asset_code=GOLD_COIN` | 404 |
| Unknown asset | `GET /balance/user_123?asset_code=RUBIES` | 404 |
| Missing asset_code | `GET /balance/user_123` | 422 |
| Blank asset_code | `GET /balance/user_123?asset_code=` | 422 |

---

### Folder 4: Transact — Happy Paths

For each request below, set a unique idempotency key (the collection-level pre-request script handles this). After each, call the balance endpoint to verify the new balance.

**TOPUP — Add credits:**
```json
POST /transact
{
  "user_id": "user_123",
  "amount": 50,
  "transaction_type": "TOPUP",
  "asset_code": "GOLD_COIN"
}
```

**BONUS — System grants credits:**
```json
POST /transact
{
  "user_id": "user_123",
  "amount": 25,
  "transaction_type": "BONUS",
  "asset_code": "GOLD_COIN"
}
```

**SPEND — User spends credits:**
```json
POST /transact
{
  "user_id": "user_123",
  "amount": 30,
  "transaction_type": "SPEND",
  "asset_code": "GOLD_COIN"
}
```

**Exact balance spend (edge case — spend everything):**
First check the balance, then send a SPEND for exactly that amount. New balance should be 0.

**Test script to add to all happy path requests:**
```javascript
pm.test("Status 200", () => pm.response.to.have.status(200));
pm.test("Has tx_id", () => {
    pm.expect(pm.response.json().tx_id).to.be.a('string').and.have.length.above(0);
});
pm.test("new_balance non-negative", () => {
    pm.expect(pm.response.json().new_balance).to.be.at.least(0);
});
pm.test("amount matches request", () => {
    pm.expect(pm.response.json().amount).to.equal(50); // adjust per test
});
// Save balance for chaining
pm.environment.set("last_balance", pm.response.json().new_balance);
pm.environment.set("last_tx_id", pm.response.json().tx_id);
```

---

### Folder 5: Transact — Error Cases

| Name | What to Do | Expected |
|---|---|---|
| Missing Idempotency-Key | Remove the header entirely | 400 |
| Reserved user_id | `user_id: "SYSTEM_TREASURY"` | 400 |
| Insufficient funds | SPEND 999999 | 400 |
| Amount zero | `amount: 0` | 422 |
| Negative amount | `amount: -100` | 422 |
| Unknown asset | `asset_code: "RUBIES"` | 404 |
| Unknown user | `user_id: "nobody"` | 404 |
| Empty body | `{}` | 422 |
| Missing user_id | `{"amount": 100, "transaction_type": "TOPUP", "asset_code": "GOLD_COIN"}` | 422 |

---

### Folder 6: Idempotency Tests (Critical)

These tests verify the core safety guarantee of the service.

**Test 1 — Replay returns same response, no second transaction:**

1. Send TOPUP 50 with key `test-idem-1` → record `tx_id` and `new_balance` from response
2. Send exact same request again with key `test-idem-1`
3. Assert: second response is identical to first (same `tx_id`, same `new_balance`)
4. Call `/transactions/user_123?asset_code=GOLD_COIN`
5. Assert: only ONE entry with that `transaction_id` exists in the transactions array

```javascript
// Test script for the replay request
pm.test("Same tx_id as original", () => {
    pm.expect(pm.response.json().tx_id).to.equal(pm.environment.get("last_tx_id"));
});
pm.test("Same new_balance as original", () => {
    pm.expect(pm.response.json().new_balance).to.equal(pm.environment.get("last_balance"));
});
```

**Test 2 — Same key, different payload returns 409:**

1. Send TOPUP 50 with key `test-idem-2`
2. Send SPEND 30 with key `test-idem-2` (different `transaction_type` and `amount`)
3. Assert: second request returns 409

**Test 3 — Different keys, same payload are independent transactions:**

1. Send TOPUP 10 with key `test-idem-3a`
2. Send TOPUP 10 with key `test-idem-3b` (same payload, different key)
3. Assert: both return 200
4. Call `/transactions/user_123?asset_code=GOLD_COIN`
5. Assert: two separate entries exist, balance increased by 20 total

---

### Folder 7: Transaction History

| Name | Request | What to Verify |
|---|---|---|
| Full history | `GET /transactions/user_123?asset_code=GOLD_COIN` | 200, array ordered newest-first |
| Correct fields | Same | Each entry has `transaction_id`, `amount`, `type`, `created_at` |
| Unknown user | `GET /transactions/nobody?asset_code=GOLD_COIN` | 404 |
| After several transact calls | Same | Count matches number of transactions you ran |

---

### End-to-End Flow Test (Collection Runner)

Run these requests in sequence using the **Postman Collection Runner** to simulate a full user lifecycle. Set delay to 0 between requests.

```
1.  GET  /health                              → 200
2.  GET  /balance/user_123?asset_code=GOLD_COIN → record initial balance
3.  POST /transact  TOPUP  50                → new_balance = initial + 50
4.  GET  /balance/user_123?asset_code=GOLD_COIN → assert = initial + 50
5.  POST /transact  BONUS  25                → new_balance = initial + 75
6.  POST /transact  SPEND  30                → new_balance = initial + 45
7.  POST /transact  SPEND  30  (same key as step 6) → same response as step 6, balance unchanged
8.  GET  /balance/user_123?asset_code=GOLD_COIN → assert = initial + 45 (not initial + 15)
9.  POST /transact  SPEND  999999            → 400 Insufficient funds
10. GET  /transactions/user_123?asset_code=GOLD_COIN → exactly 3 entries (not 4, because step 7 was replay)
```

---

## Known Limitations & Future Improvements

### Current Limitations

- **No pagination on `/transactions`:** A user with millions of transactions will return all of them in one response. This will OOM the server at scale. A `page` and `page_size` query parameter should be added.

- **No migration system:** `SQLModel.metadata.create_all()` is used on startup. This is acceptable for initial creation but cannot handle schema changes in production. `alembic` is already in `requirements.txt` but is not wired up.

- **`datetime.utcnow` deprecation:** Python 3.12+ deprecates `datetime.utcnow()` in favor of `datetime.now(timezone.utc)`. All `default_factory=datetime.utcnow` fields in `models.py` should be updated.

- **System treasury balance can go negative:** There is no check to prevent `SYSTEM_TREASURY` from going below zero when funding `TOPUP` or `BONUS` operations. An operator alert or hard check should be added.

- **SQLite concurrency:** `SELECT FOR UPDATE` is silently ignored by SQLite. The locking strategy is only effective on PostgreSQL. Do not use SQLite for load testing.

- **No `created_at` index on `LedgerEntry`:** The `/transactions` endpoint orders by `created_at` with no index. As ledger tables grow large this becomes a full table scan. Add `index=True` to `LedgerEntry.created_at`.

- **Hardcoded credentials in compose files:** `POSTGRES_PASSWORD=password` is committed to source control. Production deployments should use `.env` files (gitignored) or a secrets manager.

### Recommended Future Improvements

- Wire up Alembic migrations with a baseline `initial_schema` migration
- Add `page`/`page_size` pagination to `/transactions`
- Add a DB connectivity check to `/health` (currently only checks that the process is alive)
- Replace `datetime.utcnow` with `datetime.now(timezone.utc)` throughout models
- Add a system treasury balance guard in `/transact`
- Add an index to `LedgerEntry.created_at`
- Add structured logging (e.g. `structlog`) with `transaction_id` and `user_id` in every log line
- Add rate limiting per `user_id` to prevent abuse
- Add a `GET /transactions/{user_id}/{tx_id}` endpoint for looking up individual transactions by ID
