"""The anonymous API has a narrow contract independent of subscriber data."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.database import get_session
from app.main import PUBLIC_COVERAGE_LIMIT, app
from test_dashboard import seed_events


@pytest.fixture
def client(factory):
    def session_override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


PUBLIC_FIELDS = {
    "id",
    "title",
    "summary",
    "significance_score",
    "event_type",
    "published_at",
    "primary_link",
    "source_count",
}


def test_public_feed_needs_no_identity_and_exposes_only_public_fields(client, factory):
    seed_events(factory)
    response = client.get("/public/feed?limit=2")
    assert response.status_code == 200
    assert response.headers["cache-control"].startswith("public,")
    payload = response.json()
    assert payload["limit"] == 2 and len(payload["items"]) == 2
    assert set(payload["items"][0]) == PUBLIC_FIELDS
    assert not ({"analysis", "rank_score", "analysis_status"} & set(payload["items"][0]))


def test_public_detail_bounds_coverage_and_never_leaks_diagnostics(client, factory):
    seed_events(factory)
    response = client.get(f"/public/events/{UUID(int=10)}")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == PUBLIC_FIELDS | {"coverage", "coverage_limit"}
    assert payload["coverage_limit"] == PUBLIC_COVERAGE_LIMIT
    assert len(payload["coverage"]) <= PUBLIC_COVERAGE_LIMIT
    assert set(payload["coverage"][0]) == {"title", "source", "url"}
    assert "private" not in response.text
    assert client.get(f"/public/events/{UUID(int=14)}").status_code == 404


@pytest.mark.parametrize("query", ["limit=0", "limit=51", "offset=-1", "offset=10001"])
def test_public_feed_enforces_pagination_bounds(client, query):
    assert client.get(f"/public/feed?{query}").status_code == 422
