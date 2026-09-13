from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import event

import app.main as main
from app.database import get_session
from app.models import AnalysisCall, AnalysisRun, Article, Cluster, Source
from app.services.analysis import runner
from app.services.analysis.costs import PRICING_VERSION

HEADERS = {"X-Operator-Key": "test-key"}
FAKE_KEY = "fixture-secret-must-never-appear-in-status"
RAW_OUTPUT = "fixture-provider-output-must-not-appear-in-status"


@pytest.fixture
def status_client(factory, settings, monkeypatch):
    def session_override():
        with factory() as session:
            yield session

    def forbidden_provider(*args, **kwargs):
        pytest.fail("Status inspection must never construct a paid provider")

    settings.deepseek_api_key = SecretStr(FAKE_KEY)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "DeepSeekClient", forbidden_provider)
    main.app.dependency_overrides[get_session] = session_override
    try:
        with TestClient(main.app) as client:
            yield client
    finally:
        main.app.dependency_overrides.clear()


def seed_history(factory, count=25):
    costs = []
    with factory() as session:
        source = Source(
            name="Fixture", url="https://fixture.example/feed", type="rss", category="research"
        )
        session.add(source)
        session.flush()
        article = Article(
            source_id=source.id,
            title="Fixture event",
            url="https://fixture.example/event",
            canonical_url="https://fixture.example/event",
            url_hash="fixture-hash",
        )
        session.add(article)
        session.flush()
        cluster = Cluster(
            topic=article.title,
            primary_article_id=article.id,
            latest_published_at=datetime(2026, 9, 13, tzinfo=UTC),
        )
        session.add(cluster)
        session.flush()
        for index in range(count):
            created = datetime(2026, 9, 13, tzinfo=UTC) + timedelta(minutes=index)
            cost = (index + 1) / 1000
            costs.append(cost)
            run = AnalysisRun(
                started_at=created,
                finished_at=created + timedelta(seconds=10),
                status="succeeded",
                counts={"ready": 1},
                estimated_cost_usd=cost,
            )
            session.add(run)
            session.flush()
            session.add(
                AnalysisCall(
                    run_id=run.id,
                    cluster_id=cluster.id,
                    cache_key=f"cache-{index}",
                    stage="analysis",
                    model="deepseek-v4-pro",
                    returned_model="deepseek-v4-pro",
                    prompt_version="analysis-v1",
                    pricing_version=PRICING_VERSION,
                    status="succeeded",
                    output={"private_output": RAW_OUTPUT, "token": FAKE_KEY},
                    input_tokens=300,
                    cached_input_tokens=50,
                    output_tokens=100,
                    estimated_cost_usd=cost,
                    cost_is_upper_bound=False,
                    request_id="fixture-private-provider-request-id",
                    created_at=created,
                    finished_at=created + timedelta(seconds=10),
                )
            )
        session.commit()
    return costs


def test_analysis_status_requires_operator_key_and_never_exposes_credentials(
    status_client,
    settings,
):
    assert status_client.get("/internal/analysis").status_code == 401
    rejected = status_client.get("/internal/analysis", headers={"X-Operator-Key": "wrong"})
    assert rejected.status_code == 401
    assert FAKE_KEY not in rejected.text
    assert status_client.get("/internal/analysis?operator_api_key=test-key").status_code == 401
    settings.operator_api_key = ""
    disabled = status_client.get("/internal/analysis", headers=HEADERS)
    assert disabled.status_code == 503 and FAKE_KEY not in disabled.text


def test_analysis_status_returns_selected_config_without_secret_or_output_bodies(
    status_client,
    factory,
    settings,
):
    settings.analysis_enabled = True
    settings.analysis_budget_usd = 0.4
    settings.analysis_cluster_limit = 7
    seed_history(factory, count=1)
    response = status_client.get("/internal/analysis", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["credentials_configured"] is True
    assert data["automatic_analysis_enabled"] is True
    assert data["provider"] == "deepseek"
    assert data["summary_model"] == settings.summary_model
    assert data["analysis_model"] == settings.analysis_model
    assert data["run_budget_usd"] == 0.4 and data["cluster_limit"] == 7
    assert FAKE_KEY not in response.text and RAW_OUTPUT not in response.text
    assert "deepseek_api_key" not in data and "operator_api_key" not in data
    assert "fixture-private-provider-request-id" not in response.text
    call = data["recent_calls"][0]
    assert "output" not in call and "request_id" not in call
    assert call["pricing_version"] == PRICING_VERSION
    assert call["input_tokens"] == 300 and call["cached_input_tokens"] == 50
    assert call["output_tokens"] == 100 and call["cost_is_upper_bound"] is False


def test_analysis_status_caps_recent_history_but_cost_includes_all_attempts_and_is_read_only(
    status_client,
    factory,
):
    costs = seed_history(factory)
    statements = []
    with factory() as session:
        engine = session.bind

    def record_sql(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_sql)
    try:
        response = status_client.get("/internal/analysis", headers=HEADERS)
    finally:
        event.remove(engine, "before_cursor_execute", record_sql)
    assert response.status_code == 200
    data = response.json()
    assert len(data["runs"]) == len(data["recent_calls"]) == 20
    assert [call["estimated_cost_usd"] for call in data["recent_calls"]] == list(
        reversed(costs[-20:])
    )
    assert [run["estimated_cost_usd"] for run in data["runs"]] == list(reversed(costs[-20:]))
    assert data["estimated_total_cost_usd"] == pytest.approx(sum(costs))
    assert len(statements) == 3 and all(
        sql.lstrip().upper().startswith("SELECT") for sql in statements
    )


def test_analysis_status_missing_key_is_inspectable_with_empty_ledger(status_client, settings):
    settings.deepseek_api_key = SecretStr("")
    response = status_client.get("/internal/analysis", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["credentials_configured"] is False
    assert data["runs"] == data["recent_calls"] == []
    assert data["estimated_total_cost_usd"] == 0
    assert status_client.post("/internal/analysis", headers=HEADERS).status_code == 405
