import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from app.config import Settings
from app.models import Article, ClusterArticle, Observation, PipelineRun, Source, utcnow
from app.services.ingestion.arxiv import fetch_arxiv
from app.services.ingestion.hackernews import AI_PATTERN, fetch_hackernews
from app.services.ingestion.parsing import ArticleParser
from app.services.ingestion.rss import fetch_rss
from app.services.processing.cluster import assign_cluster, aware, refresh_cluster
from app.services.processing.dedup import canonicalize_url, hamming_distance, simhash, url_hash
from app.services.processing.embeddings import embedding_text, validate_vector


async def fetch_source(client, source, settings):
    if source.type == "arxiv":
        return await fetch_arxiv(
            client, source, settings.source_limit, settings.initial_lookback_days
        )
    if source.type == "hackernews":
        return await fetch_hackernews(client, source, settings.source_limit)
    if source.type == "rss":
        return await fetch_rss(client, source, settings.source_limit)
    raise ValueError(f"Unsupported source type: {source.type}")


def store_candidate(session, source, candidate, settings):
    canonical = canonicalize_url(candidate.url)
    external_id = candidate.external_id or canonical
    observation = session.scalar(
        select(Observation).where(
            Observation.source_id == source.id,
            Observation.external_id == external_id,
        )
    )
    article = session.get(Article, observation.article_id) if observation else None
    if article is None:
        article = session.scalar(select(Article).where(Article.url_hash == url_hash(canonical)))
    if article is None:
        # URL aliases remain exact matches even after a better publisher replaces a copy.
        article = session.scalar(
            select(Article)
            .join(Observation)
            .where(
                Observation.url_hash == url_hash(canonical),
            )
            .order_by(Article.fetched_at, Article.id)
            .limit(1)
        )
    fingerprint = simhash(candidate.body, settings.simhash_min_words)
    if article is None and fingerprint:
        # Near-duplicate matching is intentionally bounded to this news window.
        event_time = aware(candidate.published_at or utcnow())
        window_start = event_time - timedelta(days=7)
        window_end = event_time + timedelta(days=7)
        nearby = session.scalars(
            select(Article)
            .where(
                Article.content_hash.is_not(None),
                or_(
                    Article.published_at.between(window_start, window_end),
                    (Article.published_at.is_(None))
                    & Article.fetched_at.between(window_start, window_end),
                ),
            )
            .order_by(Article.fetched_at, Article.id)
        ).all()
        for possible in nearby:
            ratio = len(candidate.body.split()) / max(1, len(possible.body.split()))
            if (
                0.8 <= ratio <= 1.25
                and hamming_distance(fingerprint, possible.content_hash)
                <= settings.simhash_distance
            ):
                article = possible
                break
    created = article is None
    changed = False
    if created:
        article = Article(
            source_id=source.id,
            url=candidate.url,
            canonical_url=canonical,
            url_hash=url_hash(canonical),
            title=candidate.title,
            body=candidate.body,
            author=candidate.author,
            published_at=candidate.published_at,
            content_hash=fingerprint,
            extra=candidate.metadata,
        )
        session.add(article)
        session.flush()
    else:
        # A richer publisher feed can upgrade a URL first found as an HN headline.
        previous_source = session.get(Source, article.source_id)
        promote = source.authority_score > previous_source.authority_score
        if (canonical == article.canonical_url or promote) and (
            len(candidate.body.split()) > len(article.body.split())
        ):
            article.body, article.content_hash = candidate.body, fingerprint
            article.embedding = None
            article.embedding_model = None
            changed = True
        if promote:
            article.url = candidate.url
            article.canonical_url = canonical
            article.url_hash = url_hash(canonical)
            article.source_id = source.id
            article.title = candidate.title
            article.author = candidate.author or article.author
            article.extra = candidate.metadata
            article.embedding = None
            article.embedding_model = None
            changed = True
        if article.published_at is None and candidate.published_at:
            article.published_at = candidate.published_at
            changed = True
    new_observation = observation is None
    if new_observation:
        observation = Observation(
            article_id=article.id, source_id=source.id, external_id=external_id, url=candidate.url
        )
        session.add(observation)
    observation.extra = candidate.metadata
    observation.url_hash = url_hash(canonical)
    observation.seen_at = utcnow()
    session.flush()
    membership = session.scalar(
        select(ClusterArticle).where(ClusterArticle.article_id == article.id)
    )
    if membership and (changed or new_observation):
        refresh_cluster(session, membership.cluster_id)
    return created


async def run_pipeline(factory, settings: Settings, client, embedder, fetcher=fetch_source):
    """Caller holds the Postgres writer lock; injectable boundaries support offline tests."""
    counts = {
        "fetched": 0,
        "created": 0,
        "deduplicated": 0,
        "filtered": 0,
        "embedded": 0,
        "clustered": 0,
        "extraction_fallbacks": 0,
    }
    errors = []
    with factory() as session:
        run = PipelineRun()
        session.add(run)
        session.commit()
        run_id = run.id
        source_ids = list(
            session.scalars(
                select(Source.id)
                .where(Source.is_active.is_(True))
                .order_by(
                    Source.authority_score.desc(),
                    Source.name,
                )
            )
        )
    parser = ArticleParser(client)
    for source_id in source_ids:
        with factory() as session:
            source = session.get(Source, source_id)
            source_name = source.name
            source_errors = []
            try:
                fetched = await fetcher(client, source, settings)
                source_errors.extend(fetched.warnings)
                for candidate in fetched.items:
                    counts["fetched"] += 1
                    if candidate.published_at and (
                        aware(candidate.published_at)
                        < utcnow() - timedelta(days=settings.initial_lookback_days)
                        or aware(candidate.published_at) > utcnow() + timedelta(hours=1)
                    ):
                        counts["filtered"] += 1
                        continue
                    if source.config.get("ai_filter") and not AI_PATTERN.search(
                        candidate.title + " " + candidate.body
                    ):
                        counts["filtered"] += 1
                        continue
                    try:
                        if (
                            settings.enrich_articles
                            and source.type != "arxiv"
                            and len(candidate.body.split()) < 300
                        ):
                            try:
                                extracted = await parser.extract(candidate.url)
                                if len(extracted.split()) > len(candidate.body.split()):
                                    candidate.body = extracted
                                else:
                                    counts["extraction_fallbacks"] += 1
                            except Exception:
                                counts["extraction_fallbacks"] += 1
                        with session.begin_nested():
                            created = store_candidate(session, source, candidate, settings)
                        counts["created" if created else "deduplicated"] += 1
                    except Exception as exc:
                        source_errors.append(f"Article rejected: {type(exc).__name__}")
                # Do not commit ETag/Last-Modified after a partial run; failed items must retry.
                if not source_errors:
                    source.config = {**source.config, **fetched.state}
                    source.last_fetched_at = utcnow()
                    source.last_error = None
                else:
                    source.last_error = "; ".join(source_errors[:10])
                session.commit()
            except Exception as exc:
                session.rollback()
                source = session.get(Source, source_id)
                source.last_error = f"Source fetch failed: {type(exc).__name__}"
                session.commit()
                source_errors.append(source.last_error)
            errors.extend({"source": source_name, "error": error} for error in source_errors)

    # Raw ingestion commits before model work. A missing model does not lose articles,
    # and the next run resumes every pending embedding and membership.
    with factory() as session:
        while True:
            pending = list(
                session.scalars(
                    select(Article)
                    .where(
                        Article.embedding.is_(None),
                    )
                    .order_by(Article.fetched_at, Article.id)
                    .limit(32)
                )
            )
            if not pending:
                break
            try:
                vectors = await asyncio.to_thread(
                    embedder.encode,
                    [embedding_text(article.title, article.body) for article in pending],
                )
                if len(vectors) != len(pending):
                    raise ValueError("Embedder returned the wrong batch size")
                for article, vector in zip(pending, vectors, strict=True):
                    article.embedding = validate_vector(vector)
                    article.embedding_model = embedder.model_name
                session.commit()
                counts["embedded"] += len(pending)
            except Exception as exc:
                session.rollback()
                errors.append({"stage": "embedding", "error": str(exc)[:400]})
                break
        missing_membership = list(
            session.scalars(
                select(Article)
                .where(
                    Article.embedding.is_not(None),
                    ~Article.id.in_(select(ClusterArticle.article_id)),
                )
                .order_by(Article.published_at, Article.fetched_at, Article.id)
            )
        )
        for article in missing_membership:
            try:
                with session.begin_nested():
                    assign_cluster(session, article, settings)
                session.commit()
                counts["clustered"] += 1
            except Exception as exc:
                session.rollback()
                errors.append({"stage": "clustering", "error": str(exc)[:400]})
        run = session.get(PipelineRun, run_id)
        run.status = "partial" if errors else "succeeded"
        run.finished_at = datetime.now(UTC)
        run.counts, run.errors = counts, errors
        session.commit()
        return {"run_id": str(run_id), "status": run.status, "counts": counts, "errors": errors}
