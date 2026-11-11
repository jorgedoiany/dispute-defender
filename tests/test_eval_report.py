"""Offline tests of the T-007 report (ADR-011): labels, sections, numbers and the freeze statement."""
from __future__ import annotations

import dataclasses
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from dispute_defender.evaluation.fake import ScriptedModelClient, copying_responder, text_response
from dispute_defender.evaluation.faults import run_faults
from dispute_defender.evaluation.report import LIMITATIONS, build_report, esc
from dispute_defender.evaluation.scenarios import TruthKind, TypeTruth, load_scenarios
from dispute_defender.evaluation.scoring import scored_row

NOW = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)
HASHES = {"scenarios": "a" * 64, "scoring": "b" * 64, "prompt": "c" * 64, "pipeline": "d" * 64}
FREEZE = [{"frozen_at": "2026-11-11T01:00:00+00:00", "hashes": HASHES}]
SCENARIOS = {s.id: s for s in load_scenarios()}
FAULTS = run_faults(list(SCENARIOS.values()))
SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_evaluation.py"


def row(scenario_id: str, client: Any, model: str = "model-a", rep: int = 1, hashes: dict[str, str] = HASHES,
        run_at: str = "2026-11-11T02:00:00+00:00", scenario: Any = None) -> dict[str, Any]:
    r = scored_row(scenario or SCENARIOS[scenario_id], client, model, rep)
    r.update(run_at=run_at, hashes=hashes, author_prices=None)
    return r


def perfect() -> ScriptedModelClient:
    return ScriptedModelClient(copying_responder())


def test_report_without_live_rows_is_labelled_and_complete() -> None:
    text = build_report([], FAULTS, FREEZE, "None declared.", HASHES, NOW)
    assert text.startswith("# T-007 evaluation results: SIMULATED DATA")
    assert "do **not** describe real-world accuracy" in text
    assert "Not run yet" in text and "No live call recorded yet" in text
    assert "## Part B" in text and "Baseline: 0 of 128 correct claims wrongly rejected." in text
    assert "## Limitations" in text and all(item in text for item in LIMITATIONS)
    assert "keeps schema validation, so it is conservative and understates the verifier's value" in text


def test_part_b_table_numbers() -> None:
    text = build_report([], FAULTS, FREEZE, None, HASHES, NOW)
    s = FAULTS["summary"]["merchant_record"]
    assert f"| merchant_record | {s['applied']} | 0 | 0 | {s['expected_miss']} | {s['reached_send']} |" in text
    t = FAULTS["summary"]["tool_input"]
    assert f"| tool_input | {t['applied']} | {t['applied']} | 0 | 0 | 0 |" in text
    assert "Unexpected misses" not in text


def test_part_a_numbers_and_counterfactual() -> None:
    def wrong_amount(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{**c, "value": {**c["value"], "value": "1000.00"}} if c["type"] == "amount" else c for c in claims]

    rows = [row("N1", perfect()), row("R2", perfect()),
            row("I1", ScriptedModelClient(copying_responder(wrong_amount))),
            row("N1", ScriptedModelClient(text_response()), model="model-b")]
    text = build_report(rows, FAULTS, FREEZE, None, HASHES, NOW)
    # M2: R2's two unsupported claims + I1's wrong amount; M3: none VERIFIED, none sent.
    assert "| `model-a` | 3 | 0 | 0 |" in text
    assert "| `model-a` | 3 | 3 | 0 | 0 |" in text  # calls, accepted, rejected, errors (+ tokens follow)
    assert "| `model-b` | 1 | 0 | 1 | 0 |" in text
    assert "same model outputs" in text and "not a separate experiment" in text
    assert "1/18 (5.6%)" in text  # model errors / claims for model-a
    assert "model did not call submit\\_claims" in text  # M5 reason, escaped
    assert "Disagreements" in text


def test_wrong_but_verified_claim_shows_in_the_report() -> None:
    base = SCENARIOS["N1"]
    altered = dataclasses.replace(base, truth={**base.truth, "tracking_number": TypeTruth(TruthKind.EXPECT, ("SIMX",))})
    text = build_report([row("N1", perfect(), scenario=altered)], None, FREEZE, None, HASHES, NOW)
    assert "| `model-a` | 1 | 1 | 1 |" in text
    assert "| `model-a` | N1 | 1 | tracking_number | SIM100000001 | wrong_value | VERIFIED |" in text


def test_freeze_statement_when_frozen_before_the_run() -> None:
    text = build_report([row("N1", perfect())], None, FREEZE, "None declared.", HASHES, NOW)
    assert "They were frozen before the first live call (2026-11-11T02:00:00+00:00)" in text
    assert "No change was made after seeing results." in text
    assert "Undeclared" not in text


def test_hash_change_between_runs_is_flagged_as_undeclared() -> None:
    changed = {**HASHES, "prompt": "e" * 64}
    rows = [row("N1", perfect()), row("N2", perfect(), hashes=changed, run_at="2026-11-11T02:30:00+00:00")]
    text = build_report(rows, None, FREEZE, "# Declared changes\n\nNone declared.\n", changed, NOW)
    assert "2 different hash sets" in text
    assert "**Undeclared change" in text
    assert "No change was made" not in text


def test_declared_change_is_included_and_clears_the_warning() -> None:
    changed = {**HASHES, "scenarios": "f" * 64}
    freezes = [*FREEZE, {"frozen_at": "2026-11-11T02:10:00+00:00", "hashes": changed}]
    rows = [row("N1", perfect()), row("N2", perfect(), hashes=changed, run_at="2026-11-11T02:30:00+00:00")]
    declared = "# Declared changes\n\n2026-11-11: fixed a typo in N2's description after the first run.\n"
    text = build_report(rows, None, freezes, declared, changed, NOW)
    assert "1 later freeze(s) recorded" in text
    assert "fixed a typo in N2's description" in text
    assert "Undeclared" not in text


def test_freeze_after_first_call_is_stated() -> None:
    late = [{"frozen_at": "2026-11-11T02:30:00+00:00", "hashes": HASHES}]
    text = build_report([row("N1", perfect())], None, late, None, HASHES, NOW)
    assert "not earlier than the first live call" in text


def test_current_code_differs_from_the_run() -> None:
    text = build_report([row("N1", perfect())], None, FREEZE, None, {**HASHES, "scoring": "0" * 64}, NOW)
    assert "current code or scenarios differ" in text


def test_author_prices_give_a_labelled_cost() -> None:
    r = row("N1", perfect())
    r["author_prices"] = {"in_per_m": 2.0, "out_per_m": 10.0, "supplied_on": "2026-11-11"}
    text = build_report([r], None, FREEZE, None, HASHES, NOW)
    assert "author-supplied prices" in text and "(supplied 2026-11-11)" in text and "$0.01" in text


def test_report_without_prices_shows_no_dollars() -> None:
    text = build_report([row("N1", perfect())], FAULTS, FREEZE, None, HASHES, NOW)
    assert "$" not in text


@pytest.mark.parametrize(("raw", "expected"), [
    ("a|b", "a\\|b"), ("<script>", "&lt;script&gt;"), ("x\ny", "x y"), ("`x`", "\\`x\\`"),
])
def test_values_are_escaped_for_markdown(raw: str, expected: str) -> None:
    assert esc(raw) == expected


def test_cli_report_writes_the_file(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("run_evaluation", SCRIPT)
    assert spec and spec.loader
    cli: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    out = tmp_path / "results.md"
    assert cli.main(["report", "--raw", "--faults", str(tmp_path / "none.json"), "--out", str(out)],
                    env_file=None) == 0
    text = out.read_text()
    assert "SIMULATED DATA" in text and "Not run yet" in text
