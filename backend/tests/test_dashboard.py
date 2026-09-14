"""Customer authorization, isolation, limits, and full-set feed filtering."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.auth as auth
from app.auth import Identity, require_user, verify_user
from app.config import get_settings
from app.database import get_session
from app.main import app
from app.models import Article, Cluster, ClusterArticle, Observation, Source, User, UserTopic

ALICE = Identity(UUID(int=1), "alice@example.com")
BOB = Identity(UUID(int=2), "bob@example.com")


@pytest.fixture
def customer_client(factory, settings):
    def session_override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def as_user(identity):
    app.dependency_overrides[require_user] = lambda: identity


@pytest.mark.parametrize("path", ["/me", "/feed", f"/feed/{UUID(int=3)}"])
def test_customer_endpoints_reject_operator_key_and_missing_session(customer_client, path):
    response = customer_client.get(path, headers={"X-Operator-Key": "test-key"})
    assert response.status_code == 401
    assert response.headers["cache-control"] == "private, no-store"
    assert customer_client.put("/me/topics", json={"topics": []}).status_code == 401


def mock_auth_response(monkeypatch, settings, payload=None, status=200, raises=False):
    settings.supabase_url = "https://project.supabase.co"
    settings.supabase_publishable_key = "test-publishable"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, json=payload, request=request)
    )
    original = httpx.Client

    def client(**kwargs):
        if raises:
            raise httpx.ConnectError("offline")
        return original(transport=transport, **kwargs)

    monkeypatch.setattr(auth.httpx, "Client", client)


def user_payload(**changes):
    return {
        "id": str(ALICE.id),
        "email": ALICE.email,
        "role": "authenticated",
        "email_confirmed_at": "2026-09-14T00:00:00Z",
        "is_anonymous": False,
        **changes,
    }


def test_auth_verifies_identity_at_supabase_not_from_token_payload(monkeypatch, settings):
    requests = []
    original = httpx.Client
    settings.supabase_url = "https://project.supabase.co/"
    settings.supabase_publishable_key = "public-key"

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=user_payload(), request=request)

    monkeypatch.setattr(
        auth.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(respond), **kw)
    )
    assert verify_user("opaque-token", settings) == ALICE
    assert str(requests[0].url) == "https://project.supabase.co/auth/v1/user"
    assert requests[0].headers["authorization"] == "Bearer opaque-token"
    assert requests[0].headers["apikey"] == "public-key"


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "bad-id"},
        {"email": None},
        {"email_confirmed_at": None},
        {"is_anonymous": True},
        {"role": "service_role"},
    ],
)
def test_invalid_user_records_are_rejected(monkeypatch, settings, changes):
    mock_auth_response(monkeypatch, settings, user_payload(**changes))
    with pytest.raises(HTTPException) as error:
        verify_user("token", settings)
    assert error.value.status_code == 401


@pytest.mark.parametrize(
    "status, expected", [(401, 401), (403, 401), (429, 503), (500, 503), (302, 503)]
)
def test_supabase_failures_fail_closed(monkeypatch, settings, status, expected):
    mock_auth_response(monkeypatch, settings, status=status)
    with pytest.raises(HTTPException) as error:
        verify_user("token", settings)
    assert error.value.status_code == expected
    assert "token" not in error.value.detail


def test_auth_network_error_and_missing_configuration(monkeypatch, settings):
    with pytest.raises(HTTPException) as error:
        verify_user("token", settings)
    assert error.value.status_code == 503
    mock_auth_response(monkeypatch, settings, raises=True)
    with pytest.raises(HTTPException) as error:
        verify_user("token", settings)
    assert error.value.status_code == 503


@pytest.mark.parametrize("header", ["Basic abc", "Bearer ", "Bearer a b", "Bearer\tabc"])
def test_malformed_bearer_rejected(customer_client, header):
    assert customer_client.get("/me", headers={"Authorization": header}).status_code == 401


def test_two_users_have_isolated_topics_and_no_client_tier_escalation(customer_client, factory):
    as_user(ALICE)
    alice = customer_client.get("/me").json()
    assert alice["id"] == str(ALICE.id) and alice["topic_limit"] == 3
    assert customer_client.put("/me/topics", json={"topics": ["llm", "agents"]}).status_code == 200
    as_user(BOB)
    assert customer_client.get("/me").json()["topics"] == []
    assert customer_client.put("/me/topics", json={"topics": ["vision"]}).status_code == 200
    as_user(ALICE)
    assert customer_client.get("/me").json()["topics"] == ["agents", "llm"]
    for body in [
        {"topics": ["llm", "agents", "vision", "policy"]},
        {"topics": ["llm"], "subscription_tier": "pro"},
        {"topics": ["llm"], "user_id": str(BOB.id)},
        {"topics": ["llm", "llm"]},
        {"topics": ["unknown"]},
        {"topics": [1]},
    ]:
        assert customer_client.put("/me/topics", json=body).status_code == 422
    assert customer_client.get("/me").json()["topics"] == ["agents", "llm"]
    with factory() as session:
        assert session.get(User, ALICE.id).subscription_tier == "free"
        assert list(
            session.scalars(select(UserTopic.topic).where(UserTopic.user_id == BOB.id))
        ) == ["vision"]
    assert customer_client.put("/me/topics", json={"topics": []}).json()["topics"] == []


def seed_events(factory):
    now = datetime.now(UTC)
    with factory() as session:
        source = Source(
            name="Test source", url="https://example.com/feed", type="rss", category="research"
        )
        session.add(source)
        session.flush()
        for index, (title, age, kind) in enumerate(
            [
                ("Language model for AI agents", 1, "model_release"),
                ("A computer vision paper", 2, "paper"),
                ("Language model research: 100% coverage", 3, "paper"),
                ("Old language model", 240, "model_release"),
                ("Future language model", -24, "model_release"),
            ],
            start=10,
        ):
            article = Article(
                id=UUID(int=index + 100),
                source_id=source.id,
                title=title,
                url=f"https://example.com/{index}",
                canonical_url=f"https://example.com/{index}",
                url_hash=str(index),
                published_at=now - timedelta(hours=age),
            )
            session.add(article)
            session.flush()
            cluster = Cluster(
                id=UUID(int=index),
                topic=title,
                primary_article_id=article.id,
                latest_published_at=article.published_at,
                event_type=kind,
                significance_score=10 - index % 10,
                analysis_error="private provider diagnostics",
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
            session.add(
                Observation(
                    article_id=article.id,
                    source_id=source.id,
                    external_id=str(index),
                    url=article.url,
                    url_hash=str(index),
                    extra={"private": "diagnostic"},
                )
            )
        session.commit()


def test_feed_filters_are_applied_before_total_and_pagination(customer_client, factory):
    seed_events(factory)
    as_user(ALICE)
    assert customer_client.get("/feed?following=true").json()["total"] == 0
    customer_client.put("/me/topics", json={"topics": ["llm"]})
    page = customer_client.get("/feed?following=true&limit=1&offset=1").json()
    assert page["total"] == 2 and len(page["items"]) == 1
    assert page["items"][0]["id"] == str(UUID(int=12))
    assert "analysis_error" not in page["items"][0]
    assert customer_client.get("/feed?topic=vision").json()["total"] == 1
    assert customer_client.get("/feed?topic=llm&event_type=paper").json()["total"] == 1
    assert customer_client.get("/feed?q=%25").json()["total"] == 1
    assert customer_client.get("/feed?q=not-present").json()["total"] == 0
    assert customer_client.get("/feed?window=all&topic=llm").json()["total"] == 3
    assert customer_client.get("/feed?sort=latest").json()["items"][0]["id"] == str(UUID(int=10))
    as_user(BOB)
    assert customer_client.get("/feed?following=true").json()["total"] == 0
    detail = customer_client.get(f"/feed/{UUID(int=10)}").json()
    assert "signals" not in detail["coverage"][0]
    assert "analysis_error" not in detail
    assert customer_client.get(f"/feed/{UUID(int=999)}").status_code == 404


@pytest.mark.parametrize(
    "query", ["topic=bad", "window=bad", "limit=101", "offset=-1", "sort=bad", "event_type=bad"]
)
def test_feed_query_validation(customer_client, query):
    as_user(ALICE)
    assert customer_client.get(f"/feed?{query}").status_code == 422
