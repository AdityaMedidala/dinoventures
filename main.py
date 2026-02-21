from contextlib import asynccontextmanager
from typing import Optional
import uuid
import json
import hashlib

from fastapi import FastAPI, HTTPException, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from database import init_db, get_session
from models import Wallet, LedgerEntry, Idempotency, TransactionType, AssetType


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan, title="Internal Wallet Service")

SYSTEM_WALLET_ID = "SYSTEM_TREASURY"

#REQUEST SCHEMA
class TransactRequest(BaseModel):
    user_id: str = Field(...)
    amount: int = Field(gt=0, description="Positive integer amount")
    transaction_type: TransactionType = Field(...)
    asset_code: str = Field(min_length=1)

    class Config:
        schema_extra = {
            "example": {
                "user_id": "user_123",
                "amount": 100,
                "transaction_type": "TOPUP",
                "asset_code": "GOLD_COIN"
            }
        }


def _normalize_asset_code(code: str) -> str:
    return code.strip().upper()


def _normalize_asset_code_or_422(code: str) -> str:
    normalized = _normalize_asset_code(code)
    if not normalized:
        raise HTTPException(422, "asset_code must not be blank")
    return normalized


def _request_hash(
    user_id: str,
    amount: int,
    transaction_type: TransactionType,
    asset_code: str,
) -> str:
    payload = {
        "user_id": user_id,
        "amount": amount,
        "transaction_type": transaction_type.value,
        "asset_code": asset_code,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

#ENDPOINTS
@app.get("/health",
    response_description="Service health status",
    responses={
        200: {
            "description": "Healthy",
            "content": {"application/json": {"example": {"status": "ok"}}}
        }
    }
)
def health():
    return {"status": "ok"}


def get_wallet_or_404(
    session: Session,
    user_id: str,
    asset_code: str,
) -> tuple[Wallet, AssetType]:
    asset_code = _normalize_asset_code_or_422(asset_code)
    asset = session.exec(
        select(AssetType).where(AssetType.code == asset_code)
    ).first()
    if not asset:
        raise HTTPException(404, "Asset type not found")

    wallet = session.exec(
        select(Wallet).where(
            Wallet.user_id == user_id,
            Wallet.asset_type_id == asset.id,
        )
    ).first()
    if not wallet:
        raise HTTPException(404, "Wallet not found for user/asset")

    return wallet, asset

@app.get("/", include_in_schema=False)
def root():
    return {
        "service": "Dino Wallet Service",
        "status": "ok",
        "docs": "https://dinoventures-production.up.railway.app/docs",
        "health": "https://dinoventures-production.up.railway.app/health",
        "github": "https://github.com/AdityaMedidala/dinoventures"
    }
@app.get(
    "/balance/{user_id}",
    response_description="Current balance for the user and asset",
    responses={
        404: {"description": "Asset type or wallet not found"},
        422: {"description": "Validation error (invalid asset_code)"},
    }
)
def get_balance(
    user_id: str,
    asset_code: str = Query(..., min_length=1),
    session: Session = Depends(get_session),
):
    wallet, asset = get_wallet_or_404(session, user_id, asset_code)
    return {
        "user_id": user_id,
        "balance": wallet.balance,
        "asset_type_id": wallet.asset_type_id,
        "asset_code": asset.code,
    }


@app.get(
    "/transactions/{user_id}",
    response_description="Full transaction history for the user and asset",
    responses={
        404: {"description": "Asset type or wallet not found"},
        422: {"description": "Validation error (invalid asset_code)"},
    }
)
def get_transactions(
    user_id: str,
    asset_code: str = Query(..., min_length=1),
    session: Session = Depends(get_session),
):
    wallet, asset = get_wallet_or_404(session, user_id, asset_code)

    entries = session.exec(
        select(LedgerEntry)
        .where(LedgerEntry.wallet_id == wallet.id)
        .order_by(LedgerEntry.created_at.desc())
    ).all()

    return {
        "user_id": user_id,
        "asset_code": asset.code,
        "asset_type_id": asset.id,
        "current_balance": wallet.balance,
        "transactions": [
            {
                "transaction_id": e.transaction_id,
                "amount": e.amount,
                "type": e.reason,
                "created_at": e.created_at,
            }
            for e in entries
        ],
    }


@app.post(
    "/transact",
    response_description="Transaction completed successfully",
    responses={
        400: {"description": "Insufficient funds or invalid request"},
        404: {"description": "Asset type or wallet not found"},
        409: {"description": "Idempotency key mismatch"},
        422: {"description": "Validation error"},
    }
)

def transact(
    body: TransactRequest,
    session: Session = Depends(get_session),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise HTTPException(400, "Missing Idempotency-Key header")

    if body.user_id == SYSTEM_WALLET_ID:
        raise HTTPException(400, "SYSTEM_TREASURY is reserved")

    asset_code = _normalize_asset_code_or_422(body.asset_code)
    request_hash = _request_hash(
        user_id=body.user_id,
        amount=body.amount,
        transaction_type=body.transaction_type,
        asset_code=asset_code,
    )

    # Return cached response immediately if this key was already processed
    existing_idem = session.exec(
        select(Idempotency).where(
            Idempotency.key == idempotency_key,
            Idempotency.user_id == body.user_id,
        )
    ).first()
    if existing_idem:
        if existing_idem.request_hash != request_hash:
            raise HTTPException(409, "Idempotency-Key already used with different request")
        return json.loads(existing_idem.response_payload)

    try:
        #DEADLOCK AVOIDANCE
        asset = session.exec(select(AssetType).where(AssetType.code == asset_code)).first()
        if not asset:
            raise HTTPException(404, "Asset type not found")

        user_wallet = session.exec(
            select(Wallet).where(
                Wallet.user_id == body.user_id,
                Wallet.asset_type_id == asset.id,
            )
        ).first()
        system_wallet = session.exec(
            select(Wallet).where(
                Wallet.user_id == SYSTEM_WALLET_ID,
                Wallet.asset_type_id == asset.id,
            )
        ).first()

        if not user_wallet or not system_wallet:
            raise HTTPException(404, "Wallet not found. Run 'python seed.py' or check the setup docs")

        # Lock in consistent ID order to prevent deadlocks
        lock_first_id = min(user_wallet.id, system_wallet.id)
        lock_second_id = max(user_wallet.id, system_wallet.id)

        session.exec(select(Wallet).where(Wallet.id == lock_first_id).with_for_update()).first()
        session.exec(select(Wallet).where(Wallet.id == lock_second_id).with_for_update()).first()

        # Re-fetch after locking to get the most recent state
        user_wallet = session.exec(
            select(Wallet).where(
                Wallet.user_id == body.user_id,
                Wallet.asset_type_id == asset.id,
            ).with_for_update()
        ).first()
        system_wallet = session.exec(
            select(Wallet).where(
                Wallet.user_id == SYSTEM_WALLET_ID,
                Wallet.asset_type_id == asset.id,
            ).with_for_update()
        ).first()

        #DIRECTION: amount is always positive; SPEND debits the user
        user_delta = -body.amount if body.transaction_type == TransactionType.SPEND else body.amount
        system_delta = -user_delta  # Mirror: double-entry bookkeeping

        #BALANCE CHECK
        if user_wallet.balance + user_delta < 0:
            raise HTTPException(400, "Insufficient funds")

        #DOUBLE-ENTRY LEDGER
        tx_id = str(uuid.uuid4())

        session.add(LedgerEntry(
            transaction_id=tx_id,
            wallet_id=user_wallet.id,
            amount=user_delta,
            reason=body.transaction_type.value,
        ))
        session.add(LedgerEntry(
            transaction_id=tx_id,
            wallet_id=system_wallet.id,
            amount=system_delta,
            reason=body.transaction_type.value,
        ))

        user_wallet.balance += user_delta
        system_wallet.balance += system_delta

        session.add(user_wallet)
        session.add(system_wallet)

        response = {
            "tx_id": tx_id,
            "user_id": body.user_id,
            "transaction_type": body.transaction_type.value,
            "amount": body.amount,
            "new_balance": user_wallet.balance,
            "asset_type_id": user_wallet.asset_type_id,
            "asset_code": asset.code,
        }

        session.add(Idempotency(
            key=idempotency_key,
            user_id=body.user_id,
            request_hash=request_hash,
            response_payload=json.dumps(response),
        ))

        session.commit()
        return response

    except IntegrityError:
        # RACE CONDITIONS: two identical idempotency keys hit simultaneously.
        session.rollback()
        existing_idem = session.exec(
            select(Idempotency).where(
                Idempotency.key == idempotency_key,
                Idempotency.user_id == body.user_id,
            )
        ).first()
        if existing_idem:
            if existing_idem.request_hash != request_hash:
                raise HTTPException(409, "Idempotency-Key already used with different request")
            return json.loads(existing_idem.response_payload)
        raise

    except Exception:
        session.rollback()
        raise
