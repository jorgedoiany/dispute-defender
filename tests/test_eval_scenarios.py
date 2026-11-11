"""Offline checks of the SIMULATED evaluation scenarios (T-007, ADR-011).

The consistency tests run each scenario's own correct claims through the real verifier
and send gate. They check the scenario files, not a model; fixes to scenarios based on
them are allowed only before the first live run (see evaluation/frozen.json).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from dispute_defender.claims import Claim, Verdict
from dispute_defender.drafter import DRAFT_CLAIM_SOURCES
from dispute_defender.evaluation.pipeline import run_pipeline
from dispute_defender.evaluation.scenarios import (
    CATEGORIES,
    SCENARIO_DIR,
    ScenarioError,
    TruthKind,
    load_scenarios,
    parse_scenario,
    scenario_files,
)

SCENARIOS = load_scenarios()
IDS = [s.id for s in SCENARIOS]
PLACEHOLDER = {
    "transaction_id": "SIMPLACEHOLDER001",
    "amount": {"value": "10.00", "currency_code": "USD"},
    "transaction_date": "2026-11-09",
    "seller_protection": True,
    "tracking_number": "SIMPLACEHOLDER",
    "carrier": "FedEx",
}


def raw(name: str) -> dict[str, Any]:
    return json.loads((SCENARIO_DIR / f"{name}.json").read_text())


def test_scenario_count_and_categories() -> None:
    assert len(SCENARIOS) == 24
    assert {s.category for s in SCENARIOS} == set(CATEGORIES)


@pytest.mark.parametrize("path", scenario_files(), ids=lambda p: p.stem)
def test_every_file_is_labelled_simulated(path: Path) -> None:
    doc = json.loads(path.read_text())
    assert doc["simulated"] is True
    assert "SIMULATED" in doc["notice"]
    assert doc["id"] == path.stem


def test_unlabelled_file_is_refused() -> None:
    doc = raw("N1")
    for bad in (None, False, "true"):
        changed = copy.deepcopy(doc)
        changed["simulated"] = bad
        with pytest.raises(ScenarioError, match="simulated"):
            parse_scenario(changed)
    changed = copy.deepcopy(doc)
    del changed["simulated"]
    with pytest.raises(ScenarioError, match="simulated"):
        parse_scenario(changed)


@pytest.mark.parametrize("change", [
    lambda d: d["ground_truth"].pop("carrier"),
    lambda d: d["ground_truth"].__setitem__("delivery_date", {"absent": True}),
    lambda d: d["ground_truth"].__setitem__("amount", {"expect": []}),
    lambda d: d["ground_truth"].__setitem__("amount", {"absent": False}),
    lambda d: d["ground_truth"].__setitem__("amount", {"expect": ["1"], "absent": True}),
    lambda d: d.__setitem__("expected_send", "maybe"),
    lambda d: d.__setitem__("category", "other"),
])
def test_malformed_ground_truth_is_refused(change: Any) -> None:
    doc = copy.deepcopy(raw("N1"))
    change(doc)
    with pytest.raises(ScenarioError):
        parse_scenario(doc)


def test_no_real_looking_personal_data() -> None:
    for path in scenario_files():
        text = path.read_text()
        for message in json.loads(text)["dispute"]["messages"]:
            assert message["content"].startswith("SIMULATED")
        assert "@" not in text.replace("fake-buyer@example.invalid", "")


@pytest.mark.parametrize("scenario", SCENARIOS, ids=IDS)
def test_correct_claims_verify_and_send_outcome_matches(scenario: Any) -> None:
    result = run_pipeline(scenario.dispute, scenario.base_claims(), scenario.record)
    assert [r.verdict for r in result.results] == [Verdict.VERIFIED] * len(result.results)
    assert result.send.sent is (scenario.expected_send == "send"), result.send.reason


@pytest.mark.parametrize("scenario", SCENARIOS, ids=IDS)
def test_every_accepted_form_verifies(scenario: Any) -> None:
    for claim_type, truth in scenario.truth.items():
        for value in truth.accepted:
            claim = Claim(type=claim_type, value=value, source=DRAFT_CLAIM_SOURCES[claim_type])
            (res,) = run_pipeline(scenario.dispute, [claim], scenario.record).results
            assert res.verdict is Verdict.VERIFIED, (claim_type, value, res.reason)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=IDS)
def test_absent_and_unsupported_types_never_verify(scenario: Any) -> None:
    for claim_type, truth in scenario.truth.items():
        if truth.kind is TruthKind.EXPECT:
            continue
        value = PLACEHOLDER[claim_type]
        if truth.kind is TruthKind.UNSUPPORTED and scenario.record is not None:
            value = getattr(scenario.record, claim_type)  # the value the prompt shows the model
        claim = Claim(type=claim_type, value=value, source=DRAFT_CLAIM_SOURCES[claim_type])
        (res,) = run_pipeline(scenario.dispute, [claim], scenario.record).results
        assert res.verdict is Verdict.FLAGGED, (claim_type, res.reason)


def test_selection_by_id_and_unknown_id() -> None:
    assert [s.id for s in load_scenarios(ids=["N1", "R2"])] == ["N1", "R2"]
    with pytest.raises(ScenarioError, match="unknown"):
        load_scenarios(ids=["N1", "ZZ"])


def test_part_b_hints_present_where_needed() -> None:
    by_id = {s.id: s for s in SCENARIOS}
    assert by_id["D1"].local_date == "2026-11-09" and by_id["D2"].local_date == "2026-11-10"
    for sid in ("I1", "I2", "I3"):
        assert by_id[sid].injected_values
