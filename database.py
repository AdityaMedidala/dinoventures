import os
from typing import Generator

from sqlmodel import SQLModel, Session, create_engine

from models import Wallet, LedgerEntry, Idempotency  # noqa: F401


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./wallet.db")

engine = create_engine(DATABASE_URL, echo=False)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
