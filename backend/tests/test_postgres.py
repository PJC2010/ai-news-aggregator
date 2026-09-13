import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.database import pipeline_lock
from app.models import Article, ClusterArticle, Source, utcnow
from app.services.ingestion.types import Candidate
from app.services.pipeline import store_candidate
from app.services.processing.cluster import assign_cluster


@pytest.mark.postgres
def test_postgres_migration_vectors_constraints_and_lock(settings, embedder):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("Use a disposable database with a name ending in _test")
    directory = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=directory,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=directory,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    engine = create_engine(url)
    try:
        with pipeline_lock(engine) as first:
            assert first
            with pipeline_lock(engine) as second:
                assert not second
        with pipeline_lock(engine) as released:
            assert released
        with Session(engine) as session:
            token = str(uuid.uuid4())
            source = Source(
                name="PG integration fixture",
                url=f"https://{token}.example/feed",
                type="rss",
                category="company",
                authority_score=10,
                config={},
            )
            session.add(source)
            session.flush()
            store_candidate(
                session,
                source,
                Candidate(
                    f"https://{token}.example/release", "New language model", published_at=utcnow()
                ),
                settings,
            )
            article = session.scalar(select(Article).where(Article.source_id == source.id))
            article.embedding = embedder.encode([article.title])[0]
            article.embedding_model = embedder.model_name
            cluster = assign_cluster(session, article, settings)
            session.flush()
            dimensions = session.scalar(
                text("SELECT vector_dims(embedding) FROM articles WHERE id=:id"), {"id": article.id}
            )
            assert dimensions == 384
            assert session.scalar(
                select(ClusterArticle.is_primary).where(
                    ClusterArticle.cluster_id == cluster.id, ClusterArticle.article_id == article.id
                )
            )
            # Deliberately roll back fixture rows; migrations remain for repeatability.
            session.rollback()
    finally:
        engine.dispose()
