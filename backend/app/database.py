from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_engine():
    url = get_settings().database_url
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("The application requires PostgreSQL with the psycopg driver")
    return create_engine(url, pool_pre_ping=True)


def session_factory():
    return sessionmaker(get_engine(), expire_on_commit=False)


def get_session():
    with Session(get_engine()) as session:
        yield session


@contextmanager
def pipeline_lock(engine):
    """One writer across CLI and Celery; released even if the process disconnects."""
    with engine.connect() as connection:
        acquired = connection.scalar(text("SELECT pg_try_advisory_lock(19770301)"))
        connection.commit()
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(text("SELECT pg_advisory_unlock(19770301)"))
                connection.commit()
