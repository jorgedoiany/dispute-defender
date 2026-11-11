"""Offline tests of Part B fault injection (T-007, ADR-011). No model is called."""
from __future__ import annotations

from typing import Any

import pytest

from dispute_defender.evaluation.faults import (
    BENIGN,
    BY_DESIGN,
    CATCH,
    CLAIM_GROUPS,
    EXPECTED_MISS,
    baseline,
    claim_layer_cases,
    run_claim_layer,
    run_faults,
    run_tool_layer,
    summarize_faults,
    tool_layer_cases,
)
from dispute_defender.evaluation.scenarios import load_scenarios
from dispute_defender.evaluation.scoring import ClaimClass, classify

SCENARIOS = load_scenarios()
BY_ID = {s.id: s for s in SCENARIOS}
CLAIM_ROWS = run_claim_layer(SCENARIOS)
TOOL_ROWS = run_tool_layer(SCENARIOS)


def groups(sid: str) -> set[str]:
    return {c.group for c in claim_layer_cases(BY_ID[sid])}


def test_full_scenario_gets_every_group() -> None:
    assert groups("N1") == set(CLAIM_GROUPS) | {"benign_variant"}
    assert "local_date" in groups("D1") and "local_date" not in groups("N1")


def test_operators_apply_only_where_the_fact_exists() -> None:
    assert groups("M1") == {"tracking_carrier", "merchant_record", "source_type", "benign_variant"}
    assert groups("R1") == {"amount", "date", "transaction_id", "seller_protection", "source_type", "benign_variant"}
    assert "merchant_record" not in groups("R1")


def test_injected_values_become_faults() -> None:
    names = {c.name for c in claim_layer_cases(BY_ID["I1"])}
    assert {"value from the buyer-message injection", "tracking: one character changed"} <= names
    i3 = {c.name for c in claim_layer_cases(BY_ID["I3"])}
    assert {"tracking: value from the buyer-message injection", "carrier: value from the buyer-message injection"} <= i3


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_value_faults_really_differ_from_the_ground_truth(scenario: Any) -> None:
    """Guard: a 'fault' that is an accepted equivalent value would make the catch rate meaningless."""
    for case in claim_layer_cases(scenario):
        if case.expectation != CATCH or case.group == "source_type":
            continue
        assert classify(scenario, case.claims[case.target_index]) is ClaimClass.WRONG_VALUE, case.name


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_benign_variants_really_differ_from_the_base_value(scenario: Any) -> None:
    base = {c.type: c.value for c in scenario.base_claims()}
    for case in claim_layer_cases(scenario):
        if case.expectation == BENIGN:
            target = case.claims[case.target_index]
            assert target.value != base[target.type], case.name


def test_every_catch_fault_is_caught_and_never_sent() -> None:
    rows = [r for r in CLAIM_ROWS if r["expectation"] == CATCH]
    assert rows and all(r["verdict"] in ("FLAGGED", "BLOCKED") for r in rows)
    assert not any(r["reached_send"] for r in rows)


def test_malformed_values_are_blocked_and_source_faults_flagged() -> None:
    for r in CLAIM_ROWS:
        if r["fault"].startswith("malformed") or r["fault"] in ("string instead of boolean", "trailing space"):
            assert r["verdict"] == "BLOCKED", r
        if r["fault"].endswith(("wrong source", "no source")) or r["fault"] == "unknown claim type":
            assert r["verdict"] == "FLAGGED", r


def test_altered_merchant_record_is_an_expected_miss() -> None:
    rows = [r for r in CLAIM_ROWS if r["expectation"] == EXPECTED_MISS]
    assert rows and all(r["verdict"] == "VERIFIED" and r["outcome"] == "expected_miss" for r in rows)
    # The wrong tracking number reaches the send step whenever the scenario sends.
    sent = {r["scenario_id"] for r in rows if r["reached_send"]}
    assert "N1" in sent and "C2" not in sent


def test_benign_variants_verify_and_local_date_is_rejected_by_design() -> None:
    benign = [r for r in CLAIM_ROWS if r["expectation"] == BENIGN]
    assert benign and all(r["outcome"] == "verified" for r in benign)
    local = [r for r in CLAIM_ROWS if r["expectation"] == BY_DESIGN]
    assert {r["scenario_id"] for r in local} == {"D1", "D2"}
    assert all(r["verdict"] == "BLOCKED" and r["outcome"] == "rejected_by_design" for r in local)


def test_tool_layer_faults_are_all_rejected() -> None:
    assert len(TOOL_ROWS) == len(SCENARIOS) * len(tool_layer_cases(SCENARIOS[0]))
    assert all(r["caught"] for r in TOOL_ROWS)


def test_baseline_has_no_false_rejections() -> None:
    assert baseline(SCENARIOS) == {"correct_claims": 128, "wrongly_rejected": 0}


def test_summary_counts() -> None:
    rows = [
        {"group": "g", "outcome": "caught", "reached_send": False},
        {"group": "g", "outcome": "missed", "reached_send": True},
        {"group": "h", "outcome": "expected_miss", "reached_send": True},
    ]
    assert summarize_faults(rows) == {
        "g": {"applied": 2, "caught": 1, "missed": 1, "reached_send": 1},
        "h": {"applied": 1, "expected_miss": 1, "reached_send": 1},
    }


def test_run_faults_is_labelled_and_deterministic() -> None:
    first, second = run_faults(SCENARIOS), run_faults(SCENARIOS)
    assert first == second
    assert first["simulated"] is True and "SIMULATED" in first["notice"]
    assert first["scenario_count"] == 24
