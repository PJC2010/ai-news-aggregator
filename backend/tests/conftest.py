import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import EMBEDDING_SPACE, Settings
from app.models import Base


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def enforce_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        enrich_articles=False,
        per_host_delay_seconds=0,
        operator_api_key="test-key",
        source_limit=5,
    )


class FixtureEmbedder:
    """Known vectors test pipeline behavior, not semantic model quality."""

    model_name = EMBEDDING_SPACE

    def encode(self, texts):
        vectors = []
        for text in texts:
            vector = [0.0] * 384
            vector[0 if "language model" in text.lower() else 1] = 1.0
            vectors.append(vector)
        return vectors


@pytest.fixture
def embedder():
    return FixtureEmbedder()
