import os
from typing import Generator

from sqlmodel import SQLModel, Session, create_engine

from models import Wallet, LedgerEntry, Idempotency, AssetType  # noqa: F401


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./wallet.db")

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
