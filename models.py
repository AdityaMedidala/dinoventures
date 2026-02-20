from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class Wallet(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True, unique=True) #makes search easier
    balance: int = Field(default=0)
    currency: str = Field(default="GOLD_COIN")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LedgerEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    transaction_id: str = Field(index=True)
    wallet_id: int = Field(foreign_key="wallet.id")
    amount: int  # Positive = Credit, Negative = Debit
    reason: str  # e.g., "DEPOSIT", "SPEND"
    created_at: datetime = Field(default_factory=datetime.utcnow) #default factory for function call


class Idempotency(SQLModel, table=True):
    key: str = Field(primary_key=True)
    response_payload: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
