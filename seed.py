# seed.py
import uuid
from sqlmodel import Session, select
from database import engine, init_db
from models import Wallet, AssetType, LedgerEntry

ASSET_SEED = [
    ("GOLD_COIN", "Gold Coins"),
    ("DIAMOND", "Diamonds"),
    ("LOYALTY_POINT", "Loyalty Points"),
]

SYSTEM_WALLET_ID = "SYSTEM_TREASURY"
SYSTEM_EQUITY_ID = "SYSTEM_EQUITY"

SYSTEM_BALANCES = {
    "GOLD_COIN": 1_000_000,
    "DIAMOND": 100_000,
    "LOYALTY_POINT": 10_000_000,
}

USER_WALLETS = [
    ("user_123", "GOLD_COIN", 100),
    ("user_123", "DIAMOND", 10),
    ("user_123", "LOYALTY_POINT", 500),
    ("user_456", "GOLD_COIN", 50),
    ("user_456", "DIAMOND", 5),
]


def ensure_wallet(
    session: Session,
    user_id: str,
    asset: AssetType,
    balance: int,
) -> tuple[Wallet, bool]:
    existing = session.exec(
        select(Wallet).where(
            Wallet.user_id == user_id,
            Wallet.asset_type_id == asset.id,
        )
    ).first()

    if existing:
        return existing, False

    wallet = Wallet(
        user_id=user_id,
        balance=balance,
        asset_type_id=asset.id,
    )
    session.add(wallet)
    return wallet, True


def seed():
    init_db()

    with Session(engine) as session:
        # --- Seed asset types ---
        existing_assets = session.exec(
            select(AssetType).where(
                AssetType.code.in_([code for code, _ in ASSET_SEED])
            )
        ).all()

        existing_by_code = {asset.code: asset for asset in existing_assets}

        for code, name in ASSET_SEED:
            if code not in existing_by_code:
                session.add(AssetType(code=code, name=name))

        session.commit()

        #LOAD ASSETS
        assets_by_code = {
            asset.code: asset
            for asset in session.exec(select(AssetType)).all()
        }

        if not assets_by_code:
            print("No assets found; seed failed.")
            return

        created = []

        #SYSTEM WALLETS
        system_wallets = {}
        equity_wallets = {}
        genesis_entries: list[tuple[Wallet, Wallet, int]] = []
        for code, asset in assets_by_code.items():
            balance = SYSTEM_BALANCES.get(code, 1_000_000)
            treasury_wallet, treasury_created = ensure_wallet(
                session, SYSTEM_WALLET_ID, asset, balance
            )
            equity_wallet, equity_created = ensure_wallet(
                session, SYSTEM_EQUITY_ID, asset, 0
            )
            system_wallets[code] = treasury_wallet
            equity_wallets[code] = equity_wallet

            if treasury_created:
                created.append(f"{SYSTEM_WALLET_ID}:{code}")
                if balance != 0:
                    genesis_entries.append((treasury_wallet, equity_wallet, balance))
            if equity_created:
                created.append(f"{SYSTEM_EQUITY_ID}:{code}")

        #USER WALLETS
        user_wallets_created: list[tuple[Wallet, Wallet, int]] = []
        for user_id, code, balance in USER_WALLETS:
            asset = assets_by_code.get(code)
            if not asset:
                print(f"Missing asset {code}; skipping wallet for {user_id}.")
                continue

            wallet, created_wallet = ensure_wallet(session, user_id, asset, balance)
            if created_wallet:
                created.append(f"{user_id}:{code}")
                treasury_wallet = system_wallets.get(code)
                if treasury_wallet:
                    user_wallets_created.append((wallet, treasury_wallet, balance))

        session.flush()

        for treasury_wallet, equity_wallet, balance in genesis_entries:
            tx_id = str(uuid.uuid4())
            session.add(LedgerEntry(
                transaction_id=tx_id,
                wallet_id=treasury_wallet.id,
                amount=balance,
                reason="GENESIS",
            ))
            session.add(LedgerEntry(
                transaction_id=tx_id,
                wallet_id=equity_wallet.id,
                amount=-balance,
                reason="GENESIS",
            ))
            equity_wallet.balance -= balance

        for user_wallet, treasury_wallet, balance in user_wallets_created:
            if balance == 0:
                continue
            tx_id = str(uuid.uuid4())
            session.add(LedgerEntry(
                transaction_id=tx_id,
                wallet_id=user_wallet.id,
                amount=balance,
                reason="INITIAL_DEPOSIT",
            ))
            session.add(LedgerEntry(
                transaction_id=tx_id,
                wallet_id=treasury_wallet.id,
                amount=-balance,
                reason="INITIAL_DEPOSIT",
            ))
            treasury_wallet.balance -= balance

        session.commit()

        if created:
            print("Seeded database with assets and wallets: " + ", ".join(created))
        else:
            print("Database already seeded.")


if __name__ == "__main__":
    seed()
