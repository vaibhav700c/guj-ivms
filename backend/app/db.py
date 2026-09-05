"""Database engine / session management (PostgreSQL in prod, SQLite for dev)."""
import logging

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

def normalize_database_url(url: str) -> str:
    """Render (and Heroku) hand out `postgres://` URLs, which SQLAlchemy 2 rejects.

    Pinning the driver explicitly also stops SQLAlchemy from probing for psycopg3,
    which is not installed.
    """
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


connect_args = {}
engine_kwargs: dict = {"pool_pre_ping": True}
if settings.is_sqlite:
    connect_args = {"check_same_thread": False}
else:
    # Render's free Postgres allows few connections and the API runs as a single
    # instance — keep the pool small so a burst of dashboard requests cannot
    # exhaust it.
    engine_kwargs |= {"pool_size": 5, "max_overflow": 5, "pool_recycle": 300}

engine = create_engine(
    normalize_database_url(settings.DATABASE_URL),
    connect_args=connect_args,
    **engine_kwargs,
)

if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency — yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Base.metadata.create_all only creates tables that don't exist yet — it never
# adds columns to a table that's already live (this project has no Alembic).
# Production Postgres already has `alerts`/`anpr_events`/`watchlist` created
# from earlier deploys, so a new model column needs an explicit, idempotent
# ADD COLUMN here or every insert referencing it 500s with UndefinedColumn.
_LIGHT_MIGRATIONS = [
    ("anpr_events", "evidence_image_b64", "TEXT"),
    ("alerts", "evidence_image_b64", "TEXT"),
    # Event provenance ("edge_worker" vs "simulator") — see models.py source
    # column docstrings and CLAUDE.md "Two event sources". VARCHAR(20) is
    # valid on both SQLite (type affinity, no enforced length) and Postgres.
    ("anpr_events", "source", "VARCHAR(20) DEFAULT 'edge_worker'"),
    ("detection_events", "source", "VARCHAR(20) DEFAULT 'edge_worker'"),
    ("alerts", "source", "VARCHAR(20) DEFAULT 'edge_worker'"),
    ("camera_health_log", "source", "VARCHAR(20) DEFAULT 'edge_worker'"),
]


def run_light_migrations(bind) -> None:
    with bind.connect() as conn:
        for table, column, coltype in _LIGHT_MIGRATIONS:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
                conn.commit()
                logger.info("migration: added %s.%s", table, column)
            except Exception:
                conn.rollback()  # column already exists — expected on every later boot
