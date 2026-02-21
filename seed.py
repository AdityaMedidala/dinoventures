# seed.py
from sqlmodel import Session, select
from database import engine, init_db
from models import Wallet, AssetType

ASSET_SEED = [
    ("GOLD_COIN", "Gold Coins"),
    ("DIAMOND", "Diamonds"),
    ("LOYALTY_POINT", "Loyalty Points"),
]

SYSTEM_WALLET_ID = "SYSTEM_TREASURY"

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
) -> bool:
    existing = session.exec(
        select(Wallet).where(
            Wallet.user_id == user_id,
            Wallet.asset_type_id == asset.id,
        )
    ).first()

    if existing:
        return False

    session.add(
        Wallet(
            user_id=user_id,
            balance=balance,
            asset_type_id=asset.id,
        )
    )
    return True


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

        #SYSTEM WALLET
        for code, asset in assets_by_code.items():
            balance = SYSTEM_BALANCES.get(code, 1_000_000)
            if ensure_wallet(session, SYSTEM_WALLET_ID, asset, balance):
                created.append(f"{SYSTEM_WALLET_ID}:{code}")

        #USER WALLET
        for user_id, code, balance in USER_WALLETS:
            asset = assets_by_code.get(code)
            if not asset:
                print(f"Missing asset {code}; skipping wallet for {user_id}.")
                continue

            if ensure_wallet(session, user_id, asset, balance):
                created.append(f"{user_id}:{code}")

        session.commit()

        if created:
            print("Seeded database with assets and wallets: " + ", ".join(created))
        else:
            print("Database already seeded.")


if __name__ == "__main__":
    seed()
