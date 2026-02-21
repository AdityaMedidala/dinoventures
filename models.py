from datetime import datetime,timezone
from typing import Optional

from sqlmodel import SQLModel, Field
from sqlalchemy import UniqueConstraint

from enum import Enum


class TransactionType(str, Enum):
    TOPUP = "TOPUP"      # User buys credits
    BONUS = "BONUS"      # System grants credits
    SPEND = "SPEND"      # User spends credits


class AssetType(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)  # e.g., GOLD_COIN
    name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Wallet(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("user_id", "asset_type_id"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True) #makes search easier
    balance: int = Field(default=0)
    asset_type_id: int = Field(foreign_key="assettype.id", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LedgerEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    transaction_id: str = Field(index=True)
    wallet_id: int = Field(foreign_key="wallet.id", index=True)
    amount: int  # Positive = Credit, Negative = Debit
    reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc)) #default factory for function call


class Idempotency(SQLModel, table=True):
    key: str = Field(primary_key=True)
    user_id: str = Field(primary_key=True)
    request_hash: str
    response_payload: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
