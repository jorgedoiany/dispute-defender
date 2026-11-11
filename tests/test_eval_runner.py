"""Offline tests of the T-007 runner and CLI: spend confirmation, cap, abort, resume, freeze.

No Bedrock or PayPal call: model clients are scripted, AWS is blocked by conftest, and
the CLI is called with env_file=None so the real `.env` is never read.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from dispute_defender.drafter import ModelCallError, ModelConfigError, ModelThrottledError
from dispute_defender.evaluation import freeze as freeze_mod
from dispute_defender.evaluation.fake import ScriptedModelClient, copying_responder
from dispute_defender.evaluation.runner import (
    MAX_CALLS_CEILING,
    ModelChoice,
    build_plan,
    cap_problem,
    read_rows,
    run_plan,
)
from dispute_defender.evaluation.scenarios import SCENARIO_DIR, load_scenarios

from .conftest import FAKE_CLIENT_ID, FAKE_SECRET, FAKE_TOKEN

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_evaluation.py"
PRIMARY = "fake.primary-model"
SECONDARY = "fake.secondary-model"
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def cli() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_evaluation", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", PRIMARY)
    monkeypatch.setenv("BEDROCK_MODEL_ID_SECONDARY", SECONDARY)


@pytest.fixture
def frozen(cli: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "freeze_status", lambda: ("match", {"frozen_at": "2026-11-10T00:00:00+00:00"}))


class Factory:
    def __init__(self, *items: Any) -> None:
        self.items = items or (copying_responder(),)
        self.clients: list[ScriptedModelClient] = []

    def __call__(self, _config: Any) -> ScriptedModelClient:
        client = ScriptedModelClient(*self.items)
        self.clients.append(client)
        return client


def run_cli(cli: ModuleType, args: list[str], factory: Factory | None = None) -> int:
    return cli.main(args, client_factory=factory or Factory(), env_file=None)


# Spend confirmation and dry run


def test_run_without_confirm_spend_makes_no_client(cli: ModuleType, env: None, frozen: None, tmp_path: Path,
                                                    capsys: pytest.CaptureFixture[str]) -> None:
    factory = Factory()
    assert run_cli(cli, ["run", "--out", str(tmp_path / "raw.jsonl")], factory) == 3
    assert factory.clients == []
    assert not (tmp_path / "raw.jsonl").exists()
    assert "--confirm-spend" in capsys.readouterr().err


def test_dry_run_makes_no_client_and_prints_the_estimate(cli: ModuleType, env: None, tmp_path: Path,
                                                         capsys: pytest.CaptureFixture[str]) -> None:
    factory = Factory()
    assert run_cli(cli, ["run", "--dry-run", "--out", str(tmp_path / "raw.jsonl")], factory) == 0
    assert factory.clients == []
    out = capsys.readouterr().out
    assert "144 planned" in out and PRIMARY in out and SECONDARY in out
    assert "est. input" in out and "cost: not estimated" in out and "$" not in out
    assert "SIMULATED" in out and "no call made" in out


def test_dry_run_prints_dollars_only_with_author_prices(cli: ModuleType, env: None, tmp_path: Path,
                                                        capsys: pytest.CaptureFixture[str]) -> None:
    args = ["run", "--dry-run", "--model", "primary", "--out", str(tmp_path / "r.jsonl"),
            "--price-in-per-m", "2", "--price-out-per-m", "10"]
    assert run_cli(cli, args) == 0
    out = capsys.readouterr().out
    assert "author-supplied prices $2.0/M input, $10.0/M output" in out


@pytest.mark.parametrize("extra", [["--price-in-per-m", "2"], ["--model", "both", "--price-in-per-m", "2",
                                                               "--price-out-per-m", "10"]])
def test_price_flags_must_be_paired_and_per_model(cli: ModuleType, env: None, tmp_path: Path, extra: list[str]) -> None:
    assert run_cli(cli, ["run", "--dry-run", "--out", str(tmp_path / "r.jsonl"), *extra]) == 2


def test_dry_run_and_confirm_spend_are_exclusive(cli: ModuleType) -> None:
    with pytest.raises(SystemExit) as exc:
        run_cli(cli, ["run", "--dry-run", "--confirm-spend"])
    assert exc.value.code == 2


def test_max_calls_has_a_ceiling(cli: ModuleType) -> None:
    with pytest.raises(SystemExit):
        run_cli(cli, ["run", "--dry-run", "--max-calls", str(MAX_CALLS_CEILING + 1)])


def test_missing_model_config_fails_cleanly(cli: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_cli(cli, ["run", "--dry-run", "--out", str(tmp_path / "r.jsonl")]) == 1
    assert "ModelConfigError" in capsys.readouterr().err


# Freeze gate


def test_live_run_refused_without_matching_freeze(cli: ModuleType, env: None, tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    for status in ("missing", "differs"):
        monkeypatch.setattr(cli, "freeze_status", lambda s=status: (s, None))
        factory = Factory()
        assert run_cli(cli, ["run", "--confirm-spend", "--out", str(tmp_path / "r.jsonl")], factory) == 5
        assert factory.clients == []


def test_freeze_records_and_detects_changes(tmp_path: Path) -> None:
    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    for name in ("N1.json", "N2.json"):
        (scenarios / name).write_text((SCENARIO_DIR / name).read_text())
    path = tmp_path / "frozen.json"
    assert freeze_mod.freeze_status(path, scenarios) == ("missing", None)
    freeze_mod.freeze(NOW, path, scenarios)
    assert freeze_mod.freeze_status(path, scenarios)[0] == "match"
    (scenarios / "N2.json").write_text((SCENARIO_DIR / "N3.json").read_text())
    assert freeze_mod.freeze_status(path, scenarios)[0] == "differs"
    freeze_mod.freeze(NOW, path, scenarios)
    assert len(freeze_mod.load_freezes(path)) == 2
    assert set(freeze_mod.current_hashes(scenarios)) == {"scenarios", "scoring", "prompt", "pipeline"}


# Live path with a scripted client


def test_confirmed_run_writes_one_line_per_call(cli: ModuleType, env: None, frozen: None, tmp_path: Path) -> None:
    out = tmp_path / "raw.jsonl"
    factory = Factory()
    args = ["run", "--confirm-spend", "--scenarios", "N1,R2", "--repetitions", "2", "--out", str(out)]
    assert run_cli(cli, args, factory) == 0
    rows = read_rows(out)
    assert len(rows) == 8 and len(factory.clients) == 1 and len(factory.clients[0].requests) == 8
    assert {r["model_id"] for r in rows} == {PRIMARY, SECONDARY}
    assert all(r["simulated"] is True and r["outcome"] == "accepted" for r in rows)
    assert all(set(r["hashes"]) == {"scenarios", "scoring", "prompt", "pipeline"} for r in rows)
    assert [r["repetition"] for r in rows] == [1, 1, 1, 1, 2, 2, 2, 2]  # repetition outermost


def test_author_prices_are_recorded(cli: ModuleType, env: None, frozen: None, tmp_path: Path) -> None:
    out = tmp_path / "raw.jsonl"
    args = ["run", "--confirm-spend", "--model", "primary", "--scenarios", "N1", "--repetitions", "1",
            "--price-in-per-m", "2", "--price-out-per-m", "10", "--out", str(out)]
    assert run_cli(cli, args) == 0
    (row,) = read_rows(out)
    assert row["author_prices"]["in_per_m"] == 2 and row["author_prices"]["supplied_on"]


def test_resume_skips_completed_calls_and_retries_errors(cli: ModuleType, env: None, frozen: None, tmp_path: Path) -> None:
    out = tmp_path / "raw.jsonl"
    base = ["run", "--confirm-spend", "--model", "primary", "--scenarios", "N1,N2,N3", "--repetitions", "1",
            "--out", str(out)]
    err = ModelCallError(code="ValidationException")

    class Flaky(ScriptedModelClient):
        def converse(self, request: Any) -> Any:
            if len(self.requests) == 1:
                self.requests.append(request)
                raise err
            return super().converse(request)

    assert cli.main(base, client_factory=lambda _c: Flaky(copying_responder()), env_file=None) == 0
    rows = read_rows(out)
    assert [r["outcome"] for r in rows] == ["accepted", "error", "accepted"]

    again = Factory()
    assert cli.main([*base, "--max-calls", "4"], client_factory=again, env_file=None) == 0
    assert len(again.clients[0].requests) == 1  # only the errored call
    rows = read_rows(out)
    assert len(rows) == 4 and rows[-1]["scenario_id"] == "N2" and rows[-1]["outcome"] == "accepted"

    third = Factory()
    assert cli.main([*base, "--max-calls", "4"], client_factory=third, env_file=None) == 0
    assert third.clients == []  # nothing left to run


def test_cap_counts_earlier_attempts(cli: ModuleType, env: None, frozen: None, tmp_path: Path,
                                     capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "raw.jsonl"
    out.write_text(json.dumps({"scenario_id": "X", "model_id": PRIMARY, "repetition": 1, "outcome": "error"}) + "\n")
    factory = Factory()
    args = ["run", "--confirm-spend", "--model", "primary", "--scenarios", "N1,N2", "--repetitions", "1",
            "--max-calls", "2", "--out", str(out)]
    assert run_cli(cli, args, factory) == 5
    assert factory.clients == []
    assert "over the cap of 2" in capsys.readouterr().err


def test_cap_stops_a_run_in_progress(tmp_path: Path) -> None:
    scenarios = load_scenarios(ids=["N1", "N2", "N3"])
    plan = build_plan(scenarios, [ModelChoice("primary", PRIMARY)], 1, tmp_path / "raw.jsonl")
    assert cap_problem(plan, 2) is not None
    result = run_plan(plan, ScriptedModelClient(copying_responder()), max_calls=2, hashes={}, prices=None,
                      now=lambda: NOW, log=lambda _m: None)
    assert result.calls_made == 2 and result.aborted == "cap of 2 calls reached"


@pytest.mark.parametrize("error", [ModelThrottledError(attempts=3), ModelConfigError("AWS credentials not usable")])
def test_abort_at_once_on_throttling_or_config(cli: ModuleType, env: None, frozen: None, tmp_path: Path,
                                               error: Exception) -> None:
    out = tmp_path / "raw.jsonl"
    factory = Factory(error, copying_responder())
    args = ["run", "--confirm-spend", "--model", "primary", "--scenarios", "N1,N2", "--repetitions", "1",
            "--out", str(out)]
    assert run_cli(cli, args, factory) == 4
    assert len(read_rows(out)) == 1 and len(factory.clients[0].requests) == 1


def test_abort_after_three_errors_in_a_row(cli: ModuleType, env: None, frozen: None, tmp_path: Path) -> None:
    out = tmp_path / "raw.jsonl"
    errors = [ModelCallError(code="InternalServerException") for _ in range(3)]
    factory = Factory(*errors, copying_responder())
    args = ["run", "--confirm-spend", "--model", "primary", "--repetitions", "1", "--out", str(out)]
    assert run_cli(cli, args, factory) == 4
    assert [r["outcome"] for r in read_rows(out)] == ["error"] * 3


def test_raw_lines_hold_no_prompt_buyer_text_or_credentials(cli: ModuleType, env: None, frozen: None,
                                                            tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYPAL_CLIENT_ID", FAKE_CLIENT_ID)
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", FAKE_SECRET)
    out = tmp_path / "raw.jsonl"
    factory = Factory()
    args = ["run", "--confirm-spend", "--model", "primary", "--scenarios", "I1,I3,H1", "--repetitions", "1",
            "--out", str(out)]
    assert run_cli(cli, args, factory) == 0
    text = out.read_text()
    request = factory.clients[0].requests[0]
    for marker in ("SIMULATED buyer message", "SYSTEM OVERRIDE", request.system[:60], "<paypal_data>",
                   FAKE_CLIENT_ID, FAKE_SECRET, FAKE_TOKEN, "FAKE-BUYER"):
        assert marker not in text
