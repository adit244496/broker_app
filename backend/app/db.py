from collections.abc import Iterator
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_url = get_settings().database_url
# SQLite (tests only) needs to allow FastAPI's worker threads to share the connection.
engine = create_engine(
    _url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if _url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def add_missing_columns() -> None:
    """
    create_all() makes new tables but never alters existing ones. Columns added after a database
    was created are added here (until the project moves to Alembic migrations).
    """
    from sqlalchemy import inspect, text

    timestamp = "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME"
    added = {
        ("admin_users", "role"): "VARCHAR(10) NOT NULL DEFAULT 'admin'",
        ("registrations", "stage"): "VARCHAR(10) NOT NULL DEFAULT 'hod'",
        ("registrations", "hod_approved_by"): "VARCHAR(255)",
        ("registrations", "hod_approved_at"): timestamp,
        ("leads", "updated_at"): timestamp,
        ("leads", "site_visit_date"): "VARCHAR(40)",
        ("leads", "opportunity_id"): "VARCHAR(18)",
        ("leads", "opportunity_stage"): "VARCHAR(40)",
        ("lead_status_events", "opportunity_stage"): "VARCHAR(40)",
        ("leads", "last_changed_at"): timestamp,
        ("lead_status_events", "site_visit_date"): "VARCHAR(40)",
    }
    with engine.begin() as conn:
        tables = inspect(conn).get_table_names()
        for (table, column), ddl in added.items():
            if table in tables and column not in {c["name"] for c in inspect(conn).get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(dt: datetime) -> datetime:
    """Some drivers (SQLite in tests) return naive datetimes; treat them as UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
