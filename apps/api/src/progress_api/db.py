from collections.abc import Generator

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from progress_api.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _engine_kwargs(database_url: str) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {
            "connect_args": {
                "check_same_thread": False,
                # API requests and the video worker are separate processes.
                # Wait for a writer instead of failing immediately while a
                # long capture is committing keyframes or camera poses.
                "timeout": 60,
            }
        }
    return {"pool_pre_ping": True}


def _configure_sqlite_connection(dbapi_connection: object, _: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    try:
        # WAL lets the web API continue reading capture status while the worker
        # writes a large localization result. busy_timeout also applies to
        # locks encountered after the connection has been established.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=60000")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


settings = get_settings()
engine = create_engine(settings.database_url, **_engine_kwargs(settings.database_url))
if settings.database_url.startswith("sqlite"):
    event.listen(engine, "connect", _configure_sqlite_connection)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
