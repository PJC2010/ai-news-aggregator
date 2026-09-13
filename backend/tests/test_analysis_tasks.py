from contextlib import contextmanager
from uuid import UUID

import pytest

from app.workers import tasks


def test_analyze_once_busy_writer_prevents_provider_and_session_creation(monkeypatch):
    engine = object()
    events = []

    @contextmanager
    def busy_lock(received_engine):
        assert received_engine is engine
        events.append("lock_checked")
        try:
            yield False
        finally:
            events.append("lock_context_exited")

    def forbidden(*args, **kwargs):
        pytest.fail("A busy writer lock must prevent analysis and database-session creation")

    monkeypatch.setattr(tasks, "get_engine", lambda: engine)
    monkeypatch.setattr(tasks, "pipeline_lock", busy_lock)
    monkeypatch.setattr(tasks, "session_factory", forbidden)
    monkeypatch.setattr(tasks, "run_analysis", forbidden)
    result = tasks.analyze_once(limit=2, cluster_id=UUID(int=1))
    assert result["status"] == "skipped" and "writer lock" in result["reason"]
    assert events == ["lock_checked", "lock_context_exited"]


@pytest.mark.parametrize("fails", [False, True])
def test_analyze_once_keeps_lock_for_analysis_and_releases_it_on_return_or_error(
    monkeypatch,
    settings,
    fails,
):
    engine, factory = object(), object()
    events = []
    result = {"status": "succeeded", "counts": {"ready": 1}}

    @contextmanager
    def acquired_lock(received_engine):
        assert received_engine is engine
        events.append("locked")
        try:
            yield True
        finally:
            events.append("unlocked")

    async def analyze(received_factory, received_settings, *, limit, cluster_id):
        assert received_factory is factory and received_settings is settings
        assert (limit, cluster_id) == (2, UUID(int=1))
        assert events == ["locked"]
        events.append("analysis")
        if fails:
            raise RuntimeError("Fixture analysis failed")
        return result

    monkeypatch.setattr(tasks, "get_engine", lambda: engine)
    monkeypatch.setattr(tasks, "pipeline_lock", acquired_lock)
    monkeypatch.setattr(tasks, "session_factory", lambda: factory)
    monkeypatch.setattr(tasks, "settings", settings)
    monkeypatch.setattr(tasks, "run_analysis", analyze)
    if fails:
        with pytest.raises(RuntimeError, match="Fixture analysis failed"):
            tasks.analyze_once(limit=2, cluster_id=UUID(int=1))
    else:
        assert tasks.analyze_once(limit=2, cluster_id=UUID(int=1)) is result
    assert events == ["locked", "analysis", "unlocked"]
