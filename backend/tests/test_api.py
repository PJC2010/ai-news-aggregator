from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

import app.main as main
from app.config import get_settings
from app.database import get_session
from app.main import app
from app.models import Article, Cluster, ClusterArticle, Source

NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)
HEADERS = {"X-Operator-Key": "test-key"}


@pytest.fixture
def api_client(factory, settings, monkeypatch):
    def session_override():
        with factory() as session:
            yield session

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is not None else NOW.replace(tzinfo=None)

    app.dependency_overrides[get_session] = session_override
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "datetime", FixedDatetime)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def add_cluster(session, source, index, *, topic="Alpha", age=0, significance=None):
    article = Article(
        id=UUID(int=1000 + index),
        source_id=source.id,
        title=f"{topic} article {index}",
        url=f"https://publisher.example/{index}",
        canonical_url=f"https://publisher.example/{index}",
        url_hash=f"hash-{index}",
        published_at=NOW - timedelta(hours=age),
    )
    session.add(article)
    session.flush()
    cluster = Cluster(
        id=UUID(int=index),
        topic=topic,
        primary_article_id=article.id,
        latest_published_at=article.published_at,
        significance_score=significance,
        analysis_status="ready" if significance is not None else "pending",
        analyzed_at=NOW if significance is not None else None,
    )
    session.add(cluster)
    session.flush()
    session.add(
        ClusterArticle(
            cluster_id=cluster.id,
            article_id=article.id,
            is_primary=True,
            similarity_score=1,
        )
    )
    return cluster


def add_source(session):
    source = Source(
        name="Publisher",
        url="https://publisher.example/feed",
        type="rss",
        category="research",
        config={"fetch_mode": "rss_fallback"},
    )
    session.add(source)
    session.flush()
    return source


def test_health_auth_and_static_route_order(factory, settings):
    def session_override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = session_override
    # require_operator reads the cached settings directly.
    original = get_settings().operator_api_key
    get_settings().operator_api_key = "test-key"
    try:
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/clusters").status_code == 401
            headers = {"X-Operator-Key": "test-key"}
            today = client.get("/clusters/today", headers=headers)
            assert today.status_code == 200 and today.json()["items"] == []
            assert client.get("/clusters?limit=101", headers=headers).status_code == 422
            assert client.get("/clusters?topic=%25", headers=headers).json()["total"] == 0
            assert (
                client.get(
                    "/clusters/00000000-0000-0000-0000-000000000001", headers=headers
                ).status_code
                == 404
            )
            get_settings().operator_api_key = ""
            assert client.get("/clusters", headers=headers).status_code == 503
    finally:
        get_settings().operator_api_key = original
        app.dependency_overrides.clear()


def test_ranked_sort_is_global_and_preserves_filter_total_and_pagination(api_client, factory):
    with factory() as session:
        source = add_source(session)
        add_cluster(session, source, 1, age=2, significance=10)
        add_cluster(session, source, 2, age=1, significance=5)
        add_cluster(session, source, 3, age=0, significance=1)
        add_cluster(session, source, 4, topic="Unrelated", significance=10)
        add_cluster(session, source, 5, topic="100% Alpha", age=10, significance=1)
        session.commit()
    ranked = api_client.get("/clusters?topic=alpha&limit=1&offset=1", headers=HEADERS)
    assert ranked.status_code == 200
    data = ranked.json()
    assert (data["total"], data["limit"], data["offset"], data["sort"]) == (4, 1, 1, "ranked")
    assert [item["id"] for item in data["items"]] == [str(UUID(int=2))]
    assert data["items"][0]["analysis_status"] == "ready"
    assert data["items"][0]["analyzed_at"] is not None
    assert data["items"][0]["rank_version"] == "editorial-v1"
    latest = api_client.get("/clusters?topic=alpha&sort=latest&limit=1", headers=HEADERS).json()
    assert latest["sort"] == "latest"
    assert [item["id"] for item in latest["items"]] == [str(UUID(int=3))]
    empty_page = api_client.get("/clusters?topic=alpha&offset=100", headers=HEADERS).json()
    assert empty_page["total"] == 4 and empty_page["items"] == []
    literal_wildcard = api_client.get("/clusters?topic=%25", headers=HEADERS).json()
    assert literal_wildcard["total"] == 1
    assert literal_wildcard["items"][0]["topic"] == "100% Alpha"


def test_today_uses_utc_day_boundaries_ranking_and_pagination(api_client, factory):
    with factory() as session:
        source = add_source(session)
        add_cluster(session, source, 1, age=12, significance=10)  # inclusive UTC midnight
        add_cluster(session, source, 2, age=1, significance=1)
        add_cluster(session, source, 3, age=13, significance=10)  # yesterday
        add_cluster(session, source, 4, age=-12, significance=10)  # tomorrow midnight
        session.commit()
    data = api_client.get("/clusters/today?limit=1&offset=0", headers=HEADERS).json()
    assert data["date"] == "2026-09-13" and data["timezone"] == "UTC"
    assert data["total"] == 2
    assert data["items"][0]["id"] == str(UUID(int=1))
    second = api_client.get("/clusters/today?limit=1&offset=1", headers=HEADERS).json()
    assert second["items"][0]["id"] == str(UUID(int=2))
    latest = api_client.get("/clusters/today?sort=latest&limit=1", headers=HEADERS).json()
    assert latest["items"][0]["id"] == str(UUID(int=2))


def test_ranked_ties_are_stable_and_list_queries_are_batched(api_client, factory):
    with factory() as session:
        source = add_source(session)
        for index in reversed(range(1, 11)):
            add_cluster(session, source, index)
        session.commit()
        engine = session.bind
    statements = []

    def count_statements(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", count_statements)
    try:
        response = api_client.get("/clusters?limit=10", headers=HEADERS)
    finally:
        event.remove(engine, "before_cursor_execute", count_statements)
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == [str(UUID(int=index)) for index in range(1, 11)]
    assert all(item["analysis_status"] == "pending" for item in items)
    assert all(
        item["rank_components"]["technical_significance"]["available"] is False for item in items
    )
    assert len(statements) == 4  # count, clusters, batched provenance, batched primary articles


def test_cluster_detail_retains_persisted_status_and_read_only_rank(api_client, factory):
    with factory() as session:
        source = add_source(session)
        cluster = add_cluster(session, source, 1)
        cluster.analysis_status = "missing_credentials"
        cluster.analysis_error = "Configure the selected provider key"
        session.commit()
    data = api_client.get(f"/clusters/{UUID(int=1)}", headers=HEADERS).json()
    assert data["analysis_status"] == "missing_credentials"
    assert data["analysis_error"] == "Configure the selected provider key"
    assert data["analyzed_at"] is None
    assert data["coverage"] == []
    assert data["rank_score"] == 22.5
    assert data["rank_components"]["technical_significance"]["available"] is False
    with factory() as session:
        assert session.get(Cluster, UUID(int=1)).analysis_status == "missing_credentials"
    source_status = api_client.get("/internal/sources", headers=HEADERS).json()
    assert source_status[0]["fetch_mode"] == "rss_fallback"


@pytest.mark.parametrize("path", ["/clusters", "/clusters/today", f"/clusters/{UUID(int=1)}"])
def test_ranking_endpoints_require_operator_key(api_client, settings, path):
    assert api_client.get(path).status_code == 401
    assert api_client.get(path, headers={"X-Operator-Key": "wrong"}).status_code == 401
    settings.operator_api_key = ""
    assert api_client.get(path, headers=HEADERS).status_code == 503


@pytest.mark.parametrize("path", ["/clusters", "/clusters/today"])
@pytest.mark.parametrize("query", ["sort=unknown", "offset=-1", "limit=101", "limit=0"])
def test_invalid_ranking_and_page_parameters_are_rejected(api_client, path, query):
    assert api_client.get(f"{path}?{query}", headers=HEADERS).status_code == 422
