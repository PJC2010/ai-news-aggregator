"""Offline integration coverage for paid-attempt journaling and shared analysis caching."""

import json
from collections import deque
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.models import (
    AnalysisCall,
    AnalysisRun,
    Article,
    Cluster,
    ClusterArticle,
    Observation,
    Source,
)
from app.services.analysis import runner
from app.services.analysis.costs import PRICING_VERSION, estimate_cost, reserve_cost
from app.services.analysis.evidence import build_evidence, digest
from app.services.analysis.prompts import analysis_messages, summary_messages
from app.services.analysis.provider import Completion, ProviderError

NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)
CODE_URL = "https://github.com/fixture-lab/sparse-router"
ARTICLE_BODY = """
Fixture Laboratory published a technical report describing a sparse routing method for
language models. The authors say their training procedure selects a small subset of
experts for each token while keeping the remaining experts inactive. Their evaluation
uses a fixed collection of language understanding tasks and compares models trained
with the same number of tokens. The report describes the training schedule, hardware
configuration, and routing losses so other researchers can examine the procedure.
The team released example evaluation scripts at https://github.com/fixture-lab/sparse-router
but has not published the complete training dataset. Independent reproduction has not
yet been reported, and the results should therefore be interpreted as the authors'
measurements. Deployment cost will depend on expert placement and network overhead.
""".strip()
SUMMARY = {
    "sentences": [
        "Fixture Laboratory reports a sparse routing method for language models.",
        "The report compares models using the same training-token budget.",
        "Independent reproduction and the full training dataset remain unavailable.",
    ]
}
ANALYSIS = {
    "event_type": "paper",
    "technical_significance": 5,
    "who_should_care": ["Machine learning researchers", "Inference engineers"],
    "why_it_matters": (
        "The disclosed procedure could help researchers evaluate sparse routing tradeoffs. "
        "The authors' measurements have not been independently reproduced."
    ),
    "what_to_watch": "Watch for independent reproduction and measurements of routing overhead.",
    "code_paper_links": [CODE_URL],
    "hype_check": "accurate",
}


def completion(
    content, *, model="fixture-returned-model", finish_reason="stop", request_id="req-1"
):
    return Completion(
        content=json.dumps(content) if isinstance(content, dict) else content,
        model=model,
        input_tokens=300,
        cached_input_tokens=100,
        output_tokens=90,
        finish_reason=finish_reason,
        request_id=request_id,
    )


class FakeProvider:
    def __init__(self, *outputs, before_request=None):
        self.outputs = deque(outputs)
        self.requests = []
        self.before_request = before_request

    async def complete(self, **request):
        self.requests.append(request)
        if self.before_request:
            self.before_request(request)
        assert self.outputs, "Unexpected provider call: a cache or budget boundary was crossed"
        result = self.outputs.popleft()
        if isinstance(result, Exception):
            raise result
        return completion(result) if isinstance(result, dict) else result


@pytest.fixture
def seeded_cluster(factory):
    with factory() as session:
        source = Source(
            name="Fixture Laboratory",
            url="https://fixture.example/feed",
            type="rss",
            category="research",
            authority_score=8,
        )
        session.add(source)
        session.flush()
        article = Article(
            source_id=source.id,
            url="https://fixture.example/sparse-routing",
            canonical_url="https://fixture.example/sparse-routing",
            url_hash="fixture-hash",
            title="Fixture Laboratory describes sparse expert routing",
            body=ARTICLE_BODY,
            published_at=NOW,
        )
        session.add(article)
        session.flush()
        cluster = Cluster(
            primary_article_id=article.id,
            topic=article.title,
            latest_published_at=NOW,
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
        session.commit()
        return cluster.id


async def execute(factory, settings, cluster_id, provider):
    return await runner.run_analysis(factory, settings, provider, cluster_id=cluster_id)


def calls_for(session, run_id):
    return session.scalars(
        select(AnalysisCall)
        .where(AnalysisCall.run_id == UUID(run_id))
        .order_by(AnalysisCall.created_at, AnalysisCall.id)
    ).all()


@pytest.mark.parametrize("body", ["word " * 1300, ("x" * 100 + " ") * 200])
def test_truncated_evidence_is_explicit_and_excludes_omitted_links(factory, seeded_cluster, body):
    with factory() as session:
        cluster = session.get(Cluster, seeded_cluster)
        article = session.get(Article, cluster.primary_article_id)
        article.body = body + " https://github.com/omitted/repository"
        session.flush()
        evidence = build_evidence(session, cluster)
        assert any("truncated excerpt" in note for note in evidence["limitations"])
        assert len(evidence["articles"][0]["body"]) <= 12000
        assert len(evidence["articles"][0]["body"].split()) <= 1200
        assert "https://github.com/omitted/repository" not in evidence["allowed_links"]


async def test_two_pass_success_journals_before_requests_and_persists_audit(
    factory,
    settings,
    seeded_cluster,
):
    journaled = []

    def assert_journal_committed(request):
        with factory() as session:
            call = session.scalar(select(AnalysisCall).where(AnalysisCall.status == "started"))
            assert call is not None
            run = session.get(AnalysisRun, call.run_id)
            assert call.model == request["model"]
            assert call.cost_is_upper_bound is True
            assert call.estimated_cost_usd > 0
            assert run.estimated_cost_usd >= call.estimated_cost_usd
            journaled.append(call.stage)

    provider = FakeProvider(SUMMARY, ANALYSIS, before_request=assert_journal_committed)
    result = await execute(factory, settings, seeded_cluster, provider)
    assert result["status"] == "succeeded" and result["counts"]["ready"] == 1
    assert journaled == ["summary", "analysis"]
    assert [request["model"] for request in provider.requests] == [
        settings.summary_model,
        settings.analysis_model,
    ]
    with factory() as session:
        cluster = session.get(Cluster, seeded_cluster)
        assert cluster.analysis_status == "ready" and cluster.analysis_error is None
        assert cluster.summary == " ".join(SUMMARY["sentences"])
        assert cluster.analysis == ANALYSIS
        assert cluster.significance_score == 5 and cluster.event_type == "paper"
        assert cluster.analyzed_at is not None
        assert cluster.analysis_input_hash == runner.input_hash(
            build_evidence(session, cluster), settings
        )
        calls = calls_for(session, result["run_id"])
        assert [call.stage for call in calls] == ["summary", "analysis"]
        assert [call.prompt_version for call in calls] == [
            runner.SUMMARY_PROMPT_VERSION,
            runner.ANALYSIS_PROMPT_VERSION,
        ]
        for call in calls:
            assert call.status == "succeeded" and call.finished_at is not None
            assert (call.input_tokens, call.cached_input_tokens, call.output_tokens) == (
                300,
                100,
                90,
            )
            assert call.provider == "deepseek" and call.returned_model == "fixture-returned-model"
            assert call.request_id == "req-1" and call.pricing_version == PRICING_VERSION
            assert call.cost_is_upper_bound is False
            assert call.estimated_cost_usd == pytest.approx(estimate_cost(call.model, 300, 100, 90))
        assert result["estimated_cost_usd"] == pytest.approx(
            sum(call.estimated_cost_usd for call in calls)
        )
        persisted_run = session.get(AnalysisRun, UUID(result["run_id"]))
        assert persisted_run.counts == result["counts"] and persisted_run.finished_at is not None


async def test_exact_replay_skips_both_provider_calls_and_adds_no_billable_rows(
    factory,
    settings,
    seeded_cluster,
):
    await execute(factory, settings, seeded_cluster, FakeProvider(SUMMARY, ANALYSIS))
    replay_provider = FakeProvider()
    result = await execute(factory, settings, seeded_cluster, replay_provider)
    assert result["status"] == "succeeded" and result["counts"]["cached"] == 1
    assert result["counts"]["ready"] == 0 and result["estimated_cost_usd"] == 0
    assert replay_provider.requests == []
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisCall)) == 2
        assert calls_for(session, result["run_id"]) == []


@pytest.mark.parametrize(
    "change",
    [
        "evidence",
        "summary_model",
        "analysis_model",
        "summary_prompt",
        "analysis_prompt",
        "summary_max_tokens",
        "analysis_max_tokens",
    ],
)
async def test_changed_inputs_invalidate_appropriate_stage_caches(
    factory,
    settings,
    seeded_cluster,
    monkeypatch,
    change,
):
    await execute(factory, settings, seeded_cluster, FakeProvider(SUMMARY, ANALYSIS))
    with factory() as session:
        cluster = session.get(Cluster, seeded_cluster)
        original_hash = cluster.analysis_input_hash
        if change == "evidence":
            session.get(
                Article, cluster.primary_article_id
            ).body += " Additional evaluation scripts are now described."
            session.commit()
    if change == "summary_model":
        settings.summary_model = "deepseek-v4-pro"
    elif change == "analysis_model":
        settings.analysis_model = "deepseek-flash"
    elif change == "summary_prompt":
        monkeypatch.setattr(runner, "SUMMARY_PROMPT_VERSION", "summary-regression-v2")
    elif change == "analysis_prompt":
        monkeypatch.setattr(runner, "ANALYSIS_PROMPT_VERSION", "analysis-regression-v2")
    elif change == "summary_max_tokens":
        settings.summary_max_tokens += 128
    elif change == "analysis_max_tokens":
        settings.analysis_max_tokens += 256
    expected_stages = (
        ["summary", "analysis"]
        if change == "evidence"
        else ["summary"]
        if change.startswith("summary")
        else ["analysis"]
    )
    provider = FakeProvider(
        *[SUMMARY if stage == "summary" else ANALYSIS for stage in expected_stages]
    )
    result = await execute(factory, settings, seeded_cluster, provider)
    assert result["status"] == "succeeded" and result["counts"]["ready"] == 1
    with factory() as session:
        cluster = session.get(Cluster, seeded_cluster)
        assert cluster.analysis_input_hash != original_hash
        assert cluster.analysis_status == "ready"
        assert [call.stage for call in calls_for(session, result["run_id"])] == expected_stages
    assert len(provider.requests) == len(expected_stages)


async def test_successful_summary_is_reused_after_analysis_failure(
    factory, settings, seeded_cluster
):
    failed = await execute(
        factory,
        settings,
        seeded_cluster,
        FakeProvider(SUMMARY, ProviderError("rate_limited", "Provider rate limited the request")),
    )
    assert failed["status"] == "partial" and failed["counts"]["failed"] == 1
    with factory() as session:
        cluster = session.get(Cluster, seeded_cluster)
        assert cluster.analysis_status == "failed" and cluster.analysis is None
        assert cluster.summary == " ".join(SUMMARY["sentences"])
        assert cluster.significance_score is None and cluster.analyzed_at is None
        assert cluster.analysis_input_hash is None
    resume_provider = FakeProvider(ANALYSIS)
    resumed = await execute(factory, settings, seeded_cluster, resume_provider)
    assert resumed["counts"]["summary_cache_hits"] == 1 and resumed["counts"]["ready"] == 1
    assert len(resume_provider.requests) == 1
    assert resume_provider.requests[0]["model"] == settings.analysis_model
    with factory() as session:
        assert [call.stage for call in calls_for(session, resumed["run_id"])] == ["analysis"]
        assert session.get(Cluster, seeded_cluster).analysis_status == "ready"


@pytest.mark.parametrize("failure", ["invalid_json", "hallucinated_link", "truncation"])
async def test_failed_output_still_records_usage_and_cost_without_ready_state(
    factory,
    settings,
    seeded_cluster,
    failure,
):
    if failure == "invalid_json":
        outputs = [completion("{broken JSON")]
        expected_error = "invalid_structured_output"
    elif failure == "hallucinated_link":
        outputs = [
            SUMMARY,
            {**ANALYSIS, "code_paper_links": ["https://github.com/invented/repository"]},
        ]
        expected_error = "invalid_structured_output"
    else:
        outputs = [
            SUMMARY,
            ProviderError(
                "truncated_output",
                "Token limit reached",
                completion('{"event_type":', finish_reason="length"),
            ),
        ]
        expected_error = "truncated_output"
    result = await execute(factory, settings, seeded_cluster, FakeProvider(*outputs))
    assert result["status"] == "partial" and result["counts"]["failed"] == 1
    assert result["counts"]["ready"] == 0
    with factory() as session:
        cluster = session.get(Cluster, seeded_cluster)
        assert cluster.analysis_status == "failed" and cluster.analysis_error == expected_error
        assert cluster.analysis is None and cluster.analyzed_at is None
        assert cluster.significance_score is None and cluster.analysis_input_hash is None
        assert cluster.summary is None if failure == "invalid_json" else bool(cluster.summary)
        calls = calls_for(session, result["run_id"])
        failed = calls[-1]
        assert (
            failed.status == "failed" and failed.error == expected_error and failed.output is None
        )
        assert (failed.input_tokens, failed.cached_input_tokens, failed.output_tokens) == (
            300,
            100,
            90,
        )
        assert failed.cost_is_upper_bound is False
        assert failed.estimated_cost_usd == pytest.approx(estimate_cost(failed.model, 300, 100, 90))
        assert result["estimated_cost_usd"] == pytest.approx(
            sum(call.estimated_cost_usd for call in calls)
        )


async def test_budget_enforced_before_provider_request_and_before_billable_ledger(
    factory,
    settings,
    seeded_cluster,
):
    settings.analysis_budget_usd = 0.00000001
    provider = FakeProvider()
    result = await execute(factory, settings, seeded_cluster, provider)
    assert result["status"] == "budget_limited" and result["estimated_cost_usd"] == 0
    assert provider.requests == []
    with factory() as session:
        cluster = session.get(Cluster, seeded_cluster)
        assert cluster.analysis_status == "pending" and cluster.analysis is None
        assert "budget" in cluster.analysis_error.lower()
        assert calls_for(session, result["run_id"]) == []
    settings.analysis_budget_usd = 0.25
    resumed = await execute(factory, settings, seeded_cluster, FakeProvider(SUMMARY, ANALYSIS))
    assert resumed["status"] == "succeeded" and resumed["counts"]["ready"] == 1


async def test_budget_resume_reuses_committed_summary_without_paying_twice(
    factory,
    settings,
    seeded_cluster,
):
    with factory() as session:
        evidence = build_evidence(session, session.get(Cluster, seeded_cluster))
    first_reservation = reserve_cost(
        settings.summary_model, summary_messages(evidence), settings.summary_max_tokens
    )
    second_reservation = reserve_cost(
        settings.analysis_model,
        analysis_messages(evidence, " ".join(SUMMARY["sentences"])),
        settings.analysis_max_tokens,
    )
    assert first_reservation < second_reservation  # Budget allows pass 1, not pass 2.
    settings.analysis_budget_usd = first_reservation + 0.00000001
    provider = FakeProvider(SUMMARY)
    stopped = await execute(factory, settings, seeded_cluster, provider)
    assert stopped["status"] == "budget_limited" and len(provider.requests) == 1
    with factory() as session:
        cluster = session.get(Cluster, seeded_cluster)
        assert cluster.summary == " ".join(SUMMARY["sentences"])
        assert cluster.analysis_status == "pending" and cluster.analysis is None
        assert len(calls_for(session, stopped["run_id"])) == 1
    settings.analysis_budget_usd = 0.25
    resumed = await execute(factory, settings, seeded_cluster, FakeProvider(ANALYSIS))
    assert resumed["counts"]["summary_cache_hits"] == 1 and resumed["counts"]["ready"] == 1
    with factory() as session:
        assert [call.stage for call in calls_for(session, resumed["run_id"])] == ["analysis"]


async def test_missing_credentials_never_constructs_provider_or_billable_attempt(
    factory,
    settings,
    seeded_cluster,
    monkeypatch,
):
    settings.deepseek_api_key = SecretStr("")

    def forbidden_provider(*args, **kwargs):
        pytest.fail("Missing credentials must be detected before constructing a network client")

    monkeypatch.setattr(runner, "DeepSeekClient", forbidden_provider)
    result = await runner.run_analysis(factory, settings, cluster_id=seeded_cluster)
    assert result["status"] == "missing_credentials"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisCall)) == 0
        assert session.get(Cluster, seeded_cluster).analysis_status != "ready"


async def test_insufficient_text_clears_stale_analysis_and_avoids_provider(
    factory,
    settings,
    seeded_cluster,
):
    await execute(factory, settings, seeded_cluster, FakeProvider(SUMMARY, ANALYSIS))
    with factory() as session:
        cluster = session.get(Cluster, seeded_cluster)
        session.get(
            Article, cluster.primary_article_id
        ).body = "The publisher announced a model update."
        session.commit()
    provider = FakeProvider()
    result = await execute(factory, settings, seeded_cluster, provider)
    assert result["counts"]["insufficient_evidence"] == 1 and provider.requests == []
    with factory() as session:
        cluster = session.get(Cluster, seeded_cluster)
        assert cluster.analysis_status == "insufficient_evidence"
        assert cluster.summary is None and cluster.analysis is None
        assert cluster.significance_score is None and cluster.analyzed_at is None
        assert cluster.analysis_input_hash is None
        assert calls_for(session, result["run_id"]) == []


async def test_evidence_hash_is_deterministic_and_engagement_only_change_keeps_ready_cache(
    factory,
    settings,
    seeded_cluster,
):
    await execute(factory, settings, seeded_cluster, FakeProvider(SUMMARY, ANALYSIS))
    with factory() as session:
        cluster = session.get(Cluster, seeded_cluster)
        original_evidence = build_evidence(session, cluster)
        original_hash = runner.input_hash(original_evidence, settings)
        assert original_hash == cluster.analysis_input_hash
        assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})
        article = session.get(Article, cluster.primary_article_id)
        hn = Source(
            name="HN", url="https://hn.fixture.example", type="hackernews", category="community"
        )
        session.add(hn)
        session.flush()
        observation = Observation(
            article_id=article.id,
            source_id=hn.id,
            external_id="123",
            url=article.url,
            url_hash=article.url_hash,
            extra={"hn_item_id": 123, "hn_points": 10},
        )
        session.add(observation)
        session.commit()
        observation.extra = {"hn_item_id": 123, "hn_points": 1000, "hn_comments": 80}
        session.commit()
        assert build_evidence(session, cluster) == original_evidence
        assert runner.input_hash(build_evidence(session, cluster), settings) == original_hash
    provider = FakeProvider()
    replay = await execute(factory, settings, seeded_cluster, provider)
    assert replay["counts"]["cached"] == 1 and provider.requests == []


async def test_abandoned_journal_recovered_without_erasing_possible_charge(
    factory,
    settings,
    seeded_cluster,
):
    with factory() as session:
        old_run = AnalysisRun(status="running", estimated_cost_usd=0.03)
        session.add(old_run)
        session.flush()
        old_call = AnalysisCall(
            run_id=old_run.id,
            cluster_id=seeded_cluster,
            cache_key="abandoned-cache-key",
            stage="summary",
            model=settings.summary_model,
            prompt_version=runner.SUMMARY_PROMPT_VERSION,
            pricing_version=PRICING_VERSION,
            estimated_cost_usd=0.03,
            status="started",
            cost_is_upper_bound=True,
        )
        session.add(old_call)
        session.get(Cluster, seeded_cluster).analysis_status = "processing"
        session.commit()
        old_run_id, old_call_id = old_run.id, old_call.id
    result = await execute(factory, settings, seeded_cluster, FakeProvider(SUMMARY, ANALYSIS))
    assert result["status"] == "succeeded"
    with factory() as session:
        old_run = session.get(AnalysisRun, old_run_id)
        old_call = session.get(AnalysisCall, old_call_id)
        assert old_run.status == "interrupted" and old_run.finished_at is not None
        assert old_call.status == "failed" and old_call.error == "interrupted"
        assert old_call.finished_at is not None and old_call.cost_is_upper_bound is True
        assert old_run.estimated_cost_usd == old_call.estimated_cost_usd == 0.03
        assert old_call.output is None
        assert session.get(Cluster, seeded_cluster).analysis_status == "ready"


async def test_timeout_keeps_upper_bound_when_usage_is_unknown_without_automatic_retry(
    factory,
    settings,
    seeded_cluster,
):
    provider = FakeProvider(ProviderError("timeout", "Request timed out without known usage"))
    result = await execute(factory, settings, seeded_cluster, provider)
    assert result["status"] == "partial" and result["counts"]["failed"] == 1
    assert len(provider.requests) == 1
    expected_reservation = reserve_cost(
        settings.summary_model,
        provider.requests[0]["messages"],
        settings.summary_max_tokens,
    )
    with factory() as session:
        (call,) = calls_for(session, result["run_id"])
        assert call.status == "failed" and call.error == "timeout"
        assert call.cost_is_upper_bound is True
        assert call.input_tokens is None and call.output_tokens is None
        assert call.estimated_cost_usd == pytest.approx(expected_reservation)
        assert result["estimated_cost_usd"] == pytest.approx(expected_reservation)
        assert session.get(Cluster, seeded_cluster).analysis_status == "failed"
