from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models.

    Defined in a dedicated module so that Alembic env.py can import
    Base.metadata without triggering DATABASE_URL evaluation or engine
    creation at import time.
    """
