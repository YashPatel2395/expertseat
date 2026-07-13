import psycopg2
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_connection() -> bool:
    """Open a short-lived connection with a bounded timeout for the readiness check.

    Uses psycopg2 directly so connect_timeout is honoured without relying on
    OS-level TCP timeouts (which may be 30 s or more).
    """
    try:
        conn = psycopg2.connect(
            settings.database_url,
            connect_timeout=settings.db_connect_timeout,
        )
        conn.close()
        return True
    except Exception:
        return False
