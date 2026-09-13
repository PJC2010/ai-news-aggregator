from datetime import timedelta

from pydantic import ValidationError
from sqlalchemy import select

from app.models import AnalysisCall, AnalysisRun, Cluster, utcnow
from app.services.analysis.costs import PRICING_VERSION, estimate_cost, reserve_cost
from app.services.analysis.evidence import (
    build_evidence,
    digest,
    enough_evidence,
    validate_evidence_links,
)
from app.services.analysis.prompts import (
    ANALYSIS_PROMPT_VERSION,
    SUMMARY_PROMPT_VERSION,
    analysis_messages,
    summary_messages,
)
from app.services.analysis.provider import DeepSeekClient, ProviderError
from app.services.analysis.schemas import AnalysisOutput, SummaryOutput
from app.services.processing.cluster import invalidate_analysis


class BudgetExceeded(Exception):
    pass


def input_hash(evidence, settings):
    return digest(
        {
            "evidence": evidence,
            "summary_model": settings.summary_model,
            "analysis_model": settings.analysis_model,
            "summary_prompt": SUMMARY_PROMPT_VERSION,
            "analysis_prompt": ANALYSIS_PROMPT_VERSION,
            "summary_max_tokens": settings.summary_max_tokens,
            "analysis_max_tokens": settings.analysis_max_tokens,
        }
    )


def _record_completion(call, completion):
    call.returned_model = completion.model
    call.request_id = completion.request_id
    call.input_tokens = completion.input_tokens
    call.cached_input_tokens = completion.cached_input_tokens
    call.output_tokens = completion.output_tokens
    call.estimated_cost_usd = estimate_cost(
        call.model,
        completion.input_tokens,
        completion.cached_input_tokens,
        completion.output_tokens,
    )
    call.cost_is_upper_bound = False


async def _stage(session, run, cluster, client, settings, *, stage, messages, evidence):
    summary_stage = stage == "summary"
    model = settings.summary_model if summary_stage else settings.analysis_model
    version = SUMMARY_PROMPT_VERSION if summary_stage else ANALYSIS_PROMPT_VERSION
    max_tokens = settings.summary_max_tokens if summary_stage else settings.analysis_max_tokens
    schema = SummaryOutput if summary_stage else AnalysisOutput
    key = digest(
        {
            "provider": "deepseek",
            "stage": stage,
            "model": model,
            "prompt": version,
            "max_tokens": max_tokens,
            "messages": messages,
        }
    )
    cached = session.scalar(
        select(AnalysisCall)
        .where(AnalysisCall.cache_key == key, AnalysisCall.status == "succeeded")
        .order_by(AnalysisCall.created_at.desc(), AnalysisCall.id)
        .limit(1)
    )
    if cached:
        output = schema.model_validate(cached.output)
        if not summary_stage:
            validate_evidence_links(output, evidence)
        return output, True
    reservation = reserve_cost(model, messages, max_tokens)
    if run.estimated_cost_usd + reservation > settings.analysis_budget_usd:
        raise BudgetExceeded
    call = AnalysisCall(
        run_id=run.id,
        cluster_id=cluster.id,
        cache_key=key,
        stage=stage,
        model=model,
        prompt_version=version,
        pricing_version=PRICING_VERSION,
        estimated_cost_usd=reservation,
        cost_is_upper_bound=True,
    )
    session.add(call)
    run.estimated_cost_usd += reservation
    session.commit()  # Journal the possible charge before making the request.
    try:
        completion = await client.complete(model=model, messages=messages, max_tokens=max_tokens)
        _record_completion(call, completion)
        output = schema.model_validate_json(completion.content)
        if not summary_stage:
            validate_evidence_links(output, evidence)
        call.output = output.model_dump(mode="json")
        call.status = "succeeded"
    except ProviderError as exc:
        if exc.completion:
            _record_completion(call, exc.completion)
        call.status, call.error = "failed", exc.code
        raise
    except (ValidationError, ValueError):
        call.status, call.error = "failed", "invalid_structured_output"
        raise ProviderError(
            "invalid_structured_output", "Provider output failed evidence/schema validation"
        ) from None
    except Exception:
        call.status, call.error = "failed", "unexpected_provider_failure"
        raise ProviderError("unexpected_provider_failure", "Provider request failed") from None
    finally:
        run.estimated_cost_usd += call.estimated_cost_usd - reservation
        call.finished_at = utcnow()
        session.commit()
    return output, False


async def run_analysis(factory, settings, client=None, *, limit=None, cluster_id=None):
    """Caller holds the shared PostgreSQL writer lock; tests inject a provider."""
    if client is None:
        key = settings.deepseek_api_key.get_secret_value()
        if not key:
            return {"status": "missing_credentials", "reason": "Configure DEEPSEEK_API_KEY"}
        async with DeepSeekClient(key, timeout=settings.analysis_timeout_seconds) as provider:
            return await run_analysis(
                factory, settings, provider, limit=limit, cluster_id=cluster_id
            )
    limit = settings.analysis_cluster_limit if limit is None else limit
    if not 1 <= limit <= 100:
        raise ValueError("Analysis limit must be between 1 and 100")
    counts = {
        "ready": 0,
        "cached": 0,
        "summary_cache_hits": 0,
        "analysis_cache_hits": 0,
        "failed": 0,
        "insufficient_evidence": 0,
    }
    errors = []
    with factory() as session:
        # The caller's exclusive lock proves old running records have no live writer.
        for old in session.scalars(select(AnalysisRun).where(AnalysisRun.status == "running")):
            old.status, old.finished_at = "interrupted", utcnow()
        for old in session.scalars(select(AnalysisCall).where(AnalysisCall.status == "started")):
            old.status, old.error, old.finished_at = "failed", "interrupted", utcnow()
        run = AnalysisRun(estimated_cost_usd=0)
        session.add(run)
        session.commit()
        statement = select(Cluster).order_by(Cluster.latest_published_at.desc(), Cluster.id)
        if cluster_id:
            statement = statement.where(Cluster.id == cluster_id)
        else:
            statement = statement.where(
                Cluster.latest_published_at
                >= utcnow() - timedelta(days=settings.initial_lookback_days)
            )
        clusters = list(session.scalars(statement))
        if cluster_id and not clusters:
            run.status = "failed"
            errors.append({"error": "cluster_not_found", "cluster_id": str(cluster_id)})
        attempted = 0
        for cluster in clusters:
            evidence = build_evidence(session, cluster)
            fingerprint = input_hash(evidence, settings)
            if (
                cluster.analysis_status == "ready"
                and cluster.analysis_input_hash == fingerprint
                and cluster.summary
                and cluster.analysis
            ):
                counts["cached"] += 1
                continue
            if attempted >= limit:
                break
            if not enough_evidence(evidence):
                invalidate_analysis(cluster)
                cluster.analysis_status = "insufficient_evidence"
                cluster.analysis_error = "At least 40 words of source text are required"
                counts["insufficient_evidence"] += 1
                session.commit()
                continue
            attempted += 1
            invalidate_analysis(cluster)
            cluster.analysis_status = "processing"
            session.commit()
            try:
                summary, cached = await _stage(
                    session,
                    run,
                    cluster,
                    client,
                    settings,
                    stage="summary",
                    messages=summary_messages(evidence),
                    evidence=evidence,
                )
                counts["summary_cache_hits"] += int(cached)
                cluster.summary = " ".join(summary.sentences)
                session.commit()  # Pass 2 failure must not lose the successful summary.
                analysis, cached = await _stage(
                    session,
                    run,
                    cluster,
                    client,
                    settings,
                    stage="analysis",
                    messages=analysis_messages(evidence, cluster.summary),
                    evidence=evidence,
                )
                counts["analysis_cache_hits"] += int(cached)
                cluster.analysis = analysis.model_dump(mode="json")
                cluster.significance_score = analysis.technical_significance
                cluster.event_type = analysis.event_type
                cluster.analysis_input_hash = fingerprint
                cluster.analysis_status, cluster.analysis_error = "ready", None
                cluster.analyzed_at = utcnow()
                counts["ready"] += 1
                session.commit()
            except BudgetExceeded:
                cluster.analysis_status = "pending"
                cluster.analysis_error = "Run budget reached; resume with ai-news analyze"
                run.status = "budget_limited"
                session.commit()
                break
            except ProviderError as exc:
                cluster.analysis_status, cluster.analysis_error = "failed", exc.code
                counts["failed"] += 1
                errors.append({"cluster_id": str(cluster.id), "error": exc.code})
                session.commit()
                if exc.code in {
                    "unauthorized",
                    "insufficient_balance",
                    "rate_limited",
                    "timeout",
                    "transport_error",
                    "invalid_usage",
                    "invalid_response",
                    "unexpected_provider_failure",
                }:
                    break
        if run.status == "running":
            run.status = "partial" if errors else "succeeded"
        run.counts, run.errors, run.finished_at = counts, errors, utcnow()
        session.commit()
        return {
            "run_id": str(run.id),
            "status": run.status,
            "counts": counts,
            "errors": errors,
            "estimated_cost_usd": run.estimated_cost_usd,
            "pricing_version": PRICING_VERSION,
        }
