import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.base import Base  # noqa: F401 — re-exported for existing importers

# DATABASE_URL must be injected via environment variable (e.g. from .env)
DATABASE_URL: str = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Enable pgvector extension and initialise the database schema.

    Two code paths are taken depending on whether Alembic has ever managed this
    database before:

    * **Fresh database** (no ``alembic_version`` table): ``Base.metadata.create_all``
      provisions the base ORM-registered tables in one shot, establishing the
      initial DDL schema.  The revision pointer is then stamped to the first
      committed revision (``a1b2c3d4e5f6``) — the pure DDL migration that was
      already applied by ``create_all``.  Finally, ``command.upgrade("head")`` is
      executed so that all *subsequent* Alembic revisions are run in order.  This
      ensures every data migration (e.g. role-template seed rows in
      ``b2c3d4e5f6a7``) and every DDL migration for schema objects introduced
      after the initial baseline are applied correctly, and that
      ``alembic_version`` accurately reflects the full migration history.

    * **Existing Alembic-managed database** (``alembic_version`` table present):
      ``create_all`` is skipped (the schema already exists); only pending Alembic
      migrations are applied via ``command.upgrade``.  In this path Alembic is the
      sole DDL owner for every object it touches, so ``downgrade`` can safely
      reverse those changes without any schema/revision inconsistency.

    Migration symmetry guarantee:
      ``alembic_version`` accurately reflects the schema at every point in the
      migration lifecycle — both after upgrade and after downgrade — regardless of
      whether the database was initialised via the fresh-bootstrap or the
      existing-Alembic code path.
    """
    import app.models  # noqa: F401 — registers all ORM models with Base.metadata

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect as sa_inspect

    alembic_cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)

    # The initial DDL revision (add run_id to history) covers the base schema
    # provisioned by create_all() above.  Subsequent revisions may carry data
    # migrations (e.g. seed rows) that create_all() cannot replicate, so we
    # stamp only to this baseline and then replay remaining revisions in full.
    _INITIAL_REVISION = "a1b2c3d4e5f6"

    insp = sa_inspect(engine)
    if "alembic_version" not in insp.get_table_names():
        # Fresh database: create all base tables via ORM, stamp the initial
        # revision to acknowledge that DDL already applied, then run all
        # subsequent Alembic revisions so data migrations are never skipped.
        Base.metadata.create_all(bind=engine)
        command.stamp(alembic_cfg, _INITIAL_REVISION)
        command.upgrade(alembic_cfg, "head")
    else:
        # Existing Alembic-managed database: apply only pending migrations.
        # create_all() is intentionally omitted — Alembic is the sole DDL owner
        # in this path, keeping upgrade/downgrade fully symmetric.
        command.upgrade(alembic_cfg, "head")


def get_db():
    """FastAPI dependency that provides a SQLAlchemy session per request."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
