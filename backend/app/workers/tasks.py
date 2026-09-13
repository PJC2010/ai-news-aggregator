import asyncio

from celery import Celery

from app.config import get_settings
from app.database import get_engine, pipeline_lock, session_factory
from app.services.ingestion.http import FetchClient
from app.services.pipeline import run_pipeline
from app.services.processing.embeddings import LocalEmbedder

settings = get_settings()
celery_app = Celery("ai_news", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_soft_time_limit=3300,
    task_time_limit=3600,
    beat_schedule={
        "ingest-news": {
            "task": "app.workers.tasks.ingest",
            "schedule": settings.ingestion_interval_seconds,
        }
    },
)


async def execute_pipeline():
    async with FetchClient(settings) as client:
        return await run_pipeline(session_factory(), settings, client, LocalEmbedder())


def ingest_once():
    with pipeline_lock(get_engine()) as acquired:
        if not acquired:
            return {"status": "skipped", "reason": "Another ingestion run holds the writer lock"}
        return asyncio.run(execute_pipeline())


@celery_app.task(name="app.workers.tasks.ingest")
def ingest():
    return ingest_once()
