import json
import sys
from uuid import UUID

import pytest

from app import cli
from app.workers import tasks


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["analyze"], {"limit": None, "cluster_id": None}),
        (["analyze", "--limit", "1"], {"limit": 1, "cluster_id": None}),
        (["analyze", "--limit", "100"], {"limit": 100, "cluster_id": None}),
        (
            ["analyze", "--limit", "3", "--cluster-id", str(UUID(int=1))],
            {"limit": 3, "cluster_id": UUID(int=1)},
        ),
    ],
)
def test_analyze_cli_parses_and_forwards_operator_arguments(
    monkeypatch, capsys, arguments, expected
):
    received = []

    def analyze_once(**kwargs):
        received.append(kwargs)
        return {"status": "succeeded", "counts": {"ready": 1}}

    monkeypatch.setattr(tasks, "analyze_once", analyze_once)
    monkeypatch.setattr(sys, "argv", ["ai-news", *arguments])
    assert cli.main() is None
    assert received == [expected]
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"status": "succeeded", "counts": {"ready": 1}}
    assert captured.err == ""


@pytest.mark.parametrize("status", ["partial", "failed", "missing_credentials", "budget_limited"])
def test_analyze_cli_returns_nonzero_and_prints_inspectable_failure(monkeypatch, capsys, status):
    result = {"status": status, "reason": "Operator action required"}
    monkeypatch.setattr(tasks, "analyze_once", lambda **kwargs: result)
    monkeypatch.setattr(sys, "argv", ["ai-news", "analyze"])
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 1
    assert json.loads(capsys.readouterr().out) == result


@pytest.mark.parametrize(
    "arguments",
    [
        ["analyze", "--limit", "0"],
        ["analyze", "--limit", "101"],
        ["analyze", "--limit", "not-a-number"],
        ["analyze", "--cluster-id", "not-a-uuid"],
        ["ingest", "--limit", "1"],
        ["seed", "--cluster-id", str(UUID(int=1))],
    ],
)
def test_invalid_analyze_arguments_fail_before_any_pipeline_work(monkeypatch, capsys, arguments):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid CLI arguments must not start pipeline work")

    monkeypatch.setattr(tasks, "analyze_once", forbidden)
    monkeypatch.setattr(tasks, "ingest_once", forbidden)
    monkeypatch.setattr(cli, "session_factory", forbidden)
    monkeypatch.setattr(sys, "argv", ["ai-news", *arguments])
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "error:" in captured.err


def test_busy_writer_is_reported_as_a_nonfailure_skip(monkeypatch, capsys):
    result = {"status": "skipped", "reason": "Another pipeline run holds the writer lock"}
    monkeypatch.setattr(tasks, "analyze_once", lambda **kwargs: result)
    monkeypatch.setattr(sys, "argv", ["ai-news", "analyze"])
    assert cli.main() is None
    assert json.loads(capsys.readouterr().out) == result
