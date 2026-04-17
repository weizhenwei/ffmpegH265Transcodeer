from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import Base


class Database:
    def __init__(self, url: str) -> None:
        is_sqlite = url.startswith("sqlite:")
        connect_args = {"check_same_thread": False, "timeout": 30} if is_sqlite else {}
        self.engine = create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)

        if is_sqlite:
            # Improve SQLite behavior for local multi-process verification.
            @event.listens_for(self.engine, "connect")
            def _set_sqlite_pragma(dbapi_connection, _connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.execute("PRAGMA busy_timeout=30000;")
                cursor.close()

        self.session_factory = sessionmaker(
            bind=self.engine, autocommit=False, autoflush=False, future=True, expire_on_commit=False
        )

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
