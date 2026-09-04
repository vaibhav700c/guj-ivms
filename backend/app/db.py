"""Database engine / session management (PostgreSQL in prod, SQLite for dev)."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

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
