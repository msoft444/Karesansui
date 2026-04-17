import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# DATABASE_URL must be injected via environment variable (e.g. from .env)
DATABASE_URL: str = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


def init_db() -> None:
    """Enable pgvector extension and create all tables.

    Models are imported here (local import) to register them with Base.metadata
    before create_all() runs, avoiding circular imports at module load time.
    """
    import app.models  # noqa: F401 — registers History & GlobalSettings with Base.metadata

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency that provides a SQLAlchemy session per request."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
