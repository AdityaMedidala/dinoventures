from fastapi import FastAPI, HTTPException, Depends
from sqlmodel import Session, select
from database import init_db, get_session
from models import Wallet, LedgerEntry
import uuid
from contextlib import asynccontextmanager


# This 'lifespan' tells the database to wake up when the app starts
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


# This is the 'app' variable that Docker was looking for!
app = FastAPI(lifespan=lifespan)


# --- HELPER: SEED DATA (Run this once to create users) ---
@app.post("/seed")
def seed_data(session: Session = Depends(get_session)):
    # Check if we already have a treasury
    existing = session.exec(select(Wallet).where(Wallet.user_id == "SYSTEM_TREASURY")).first()
    if not existing:
        treasury = Wallet(user_id="SYSTEM_TREASURY", balance=1_000_000)
        user1 = Wallet(user_id="user_123", balance=100)
        user2 = Wallet(user_id="user_456", balance=50)
        session.add(treasury)
        session.add(user1)
        session.add(user2)
        session.commit()
        return {"message": "Database seeded with Treasury, user_123, and user_456"}
    return {"message": "Database was already seeded"}


# --- FEATURE 1: CHECK BALANCE ---
@app.get("/balance/{user_id}")
def get_balance(user_id: str, session: Session = Depends(get_session)):
    wallet = session.exec(select(Wallet).where(Wallet.user_id == user_id)).first()
    if not wallet:
        raise HTTPException(404, "User not found")
    return {"user_id": user_id, "balance": wallet.balance, "currency": wallet.currency}


# --- FEATURE 2: TRANSACTION (The Hard Part) ---
@app.post("/transact")
def transact(
        user_id: str,
        amount: int,
        type: str,
        session: Session = Depends(get_session)
):
    try:
        # 1. LOCKING: We lock the wallet row so no one else can touch it
        # until we are done. This prevents the "Race Condition".
        user_wallet = session.exec(
            select(Wallet).where(Wallet.user_id == user_id).with_for_update()
        ).first()

        system_wallet = session.exec(
            select(Wallet).where(Wallet.user_id == "SYSTEM_TREASURY").with_for_update()
        ).first()

        if not user_wallet or not system_wallet:
            raise HTTPException(404, "Wallet not found. Did you run /seed?")

        # 2. LOGIC: Check Balance (Don't let them go negative)
        if amount < 0 and (user_wallet.balance + amount < 0):
            raise HTTPException(400, "Insufficient Funds")

        # 3. LEDGER: Double Entry Bookkeeping
        tx_id = str(uuid.uuid4())

        # Entry 1: The User's Side
        session.add(LedgerEntry(
            transaction_id=tx_id, wallet_id=user_wallet.id, amount=amount, reason=type
        ))
        user_wallet.balance += amount

        # Entry 2: The System's Side (Mirror the transaction)
        session.add(LedgerEntry(
            transaction_id=tx_id, wallet_id=system_wallet.id, amount=-amount, reason=type
        ))
        system_wallet.balance -= amount

        session.add(user_wallet)
        session.add(system_wallet)

        # 4. COMMIT: Save everything at once
        session.commit()
        session.refresh(user_wallet)
        return {"new_balance": user_wallet.balance, "tx_id": tx_id}

    except Exception as e:
        session.rollback()  # If anything fails, undo everything
        raise e