"""Offline tests of the T-007 scoring rules (ADR-011) with scripted model clients. No model is called."""
from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest

from dispute_defender.claims import Claim
from dispute_defender.drafter import ModelNetworkError
from dispute_defender.evaluation.fake import (
    ScriptedModelClient,
    copying_responder,
    text_response,
    tool_response,
)
from dispute_defender.evaluation.scenarios import TruthKind, TypeTruth, load_scenarios
from dispute_defender.evaluation.scoring import (
    ClaimClass,
    classify,
    scored_row,
    shown,
    summarize,
)

MODEL = "fake-model-a"
SCENARIOS = {s.id: s for s in load_scenarios()}


def rows_for(client: ScriptedModelClient, ids: list[str] | None = None, reps: int = 1,
             model: str = MODEL) -> list[dict[str, Any]]:
    chosen = [SCENARIOS[i] for i in ids] if ids else list(SCENARIOS.values())
    return [scored_row(s, client, model, rep) for rep in range(1, reps + 1) for s in chosen]


def perfect() -> ScriptedModelClient:
    return ScriptedModelClient(copying_responder())


def test_perfect_model_makes_no_model_errors() -> None:
    summary = summarize(rows_for(perfect()))["models"][MODEL]
    assert summary["accepted"] == 24 and summary["rejected"] == summary["errors"] == 0
    assert summary["model_errors"] == 0 and summary["duplicates"] == 0
    assert summary["correct_flagged"] == summary["correct_blocked"] == 0
    # R2: the record is for another transaction; an ideal copier still claims tracking and carrier.
    assert summary["classes"][ClaimClass.UNSUPPORTED] == 2
    assert summary["incorrect_counterfactual_sent"] == 2
    assert summary["incorrect_verified"] == 0 and summary["incorrect_reached_send"] == 0
    assert summary["send_mismatches"] == []
    assert summary["missing_expected"] == 0
    assert summary["crosstab"][ClaimClass.UNSUPPORTED] == {"FLAGGED": 2}


def test_erring_model_is_counted_and_stopped() -> None:
    def mutate(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for c in claims:
            if c["type"] == "amount":
                c = {**c, "value": {**c["value"], "value": "1000.00"}}  # as the I1 injection asks
            out.append(c)
        out.append({"type": "tracking_number", "source": "merchant_record", "value": "999"})  # duplicate
        return out

    rows = rows_for(ScriptedModelClient(copying_responder(mutate)), ["N1", "I1"])
    summary = summarize(rows)["models"][MODEL]
    assert summary["classes"][ClaimClass.WRONG_VALUE] == 4  # amount and the extra tracking, in both
    assert summary["duplicates"] == 2
    assert summary["model_errors"] == 4  # each extra tracking claim is wrong and a duplicate: counted once
    assert summary["drafts_with_model_error"] == 2
    assert summary["incorrect_counterfactual_sent"] == 4
    assert summary["incorrect_verified"] == 0 and summary["incorrect_reached_send"] == 0
    assert summary["crosstab"][ClaimClass.WRONG_VALUE] == {"BLOCKED": 4}
    assert summary["per_category"]["prompt_injection"]["model_errors"] == 2


def test_claim_about_a_missing_fact_is_a_model_error() -> None:
    claim = {"type": "transaction_id", "source": "paypal", "value": "SIMFAKETXN0000999"}
    client = ScriptedModelClient(copying_responder(lambda claims: [claim, *claims]))
    summary = summarize(rows_for(client, ["M1"]))["models"][MODEL]
    assert summary["classes"][ClaimClass.ABSENT_FACT] == 1
    assert summary["model_errors"] == 1
    assert summary["crosstab"][ClaimClass.ABSENT_FACT] == {"FLAGGED": 1}


def test_rejected_output_is_counted_before_the_verifier() -> None:
    client = ScriptedModelClient(text_response(), tool_response({"claims": []}), tool_response({"x": 1}, uses=2))
    rows = rows_for(client, ["N1", "N2", "N3"])
    summary = summarize(rows)["models"][MODEL]
    assert summary["rejected"] == 3 and summary["accepted"] == 0 and summary["claims"] == 0
    assert sum(summary["rejected_reasons"].values()) == 3
    assert all(r["claims"] == [] and r["send"] is None for r in rows)


def test_call_errors_are_excluded_from_rates() -> None:
    client = ScriptedModelClient(ModelNetworkError("Bedrock Converse network error: ReadTimeoutError"),
                                 copying_responder())
    rows = [scored_row(SCENARIOS["N1"], client, MODEL, rep) for rep in (1, 2)]
    summary = summarize(rows)["models"][MODEL]
    assert summary["errors"] == 1 and summary["error_types"] == {"ModelNetworkError": 1}
    assert summary["accepted"] == 1 and summary["claims"] == 6


def test_wrong_but_verified_claim_is_reported() -> None:
    """The metric is not hard-wired to 0: when the ground truth and the record disagree,
    the verifier VERIFIES a claim the ground truth calls wrong, and the report must show it."""
    base = SCENARIOS["N1"]
    altered = dataclasses.replace(
        base, truth={**base.truth, "tracking_number": TypeTruth(TruthKind.EXPECT, ("SIMREALTRACKING",))})
    row = scored_row(altered, perfect(), MODEL, 1)
    summary = summarize([row])["models"][MODEL]
    assert summary["incorrect_verified"] == 1
    assert summary["incorrect_reached_send"] == 1
    (dis,) = summary["disagreements"]
    assert dis["type"] == "tracking_number" and dis["verdict"] == "VERIFIED" and dis["truth"] == "wrong_value"


def test_correct_claim_rejected_is_a_false_rejection() -> None:
    base = SCENARIOS["D1"]
    # Ground truth that (wrongly) also accepts the local date: the verifier BLOCKS it (UTC rule).
    altered = dataclasses.replace(
        base, truth={**base.truth, "transaction_date": TypeTruth(TruthKind.EXPECT, ("2026-11-10", "2026-11-09"))})

    def local(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{**c, "value": "2026-11-09"} if c["type"] == "transaction_date" else c for c in claims]

    row = scored_row(altered, ScriptedModelClient(copying_responder(local)), MODEL, 1)
    summary = summarize([row])["models"][MODEL]
    assert summary["correct_blocked"] == 1
    assert summary["disagreements"][0]["verdict"] == "BLOCKED"


def test_variation_across_repetitions() -> None:
    calls = {"n": 0}

    def flip(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
        calls["n"] += 1
        return claims if calls["n"] % 2 else [c for c in claims if c["type"] != "seller_protection"]

    rows = rows_for(ScriptedModelClient(copying_responder(flip)), ["N1"], reps=3)
    rows += rows_for(perfect(), ["N2"], reps=3)
    rows += rows_for(perfect(), ["N3"], reps=1)
    variation = summarize(rows)["models"][MODEL]["variation"]
    assert variation["identical"] == 1
    assert variation["too_few_repetitions"] == 1
    assert variation["varying"] == [{"scenario_id": "N1", "types": ["seller_protection"], "outcomes": ["accepted"]}]


def test_send_mismatch_when_model_omits_tracking() -> None:
    client = ScriptedModelClient(copying_responder(lambda cs: [c for c in cs if c["type"] != "tracking_number"]))
    summary = summarize(rows_for(client, ["N1"]))["models"][MODEL]
    (mismatch,) = summary["send_mismatches"]
    assert mismatch["expected"] == "send" and mismatch["sent"] is False
    assert summary["missing_expected"] == 1 and summary["expected_claims"] == 6


def test_models_are_summarized_separately() -> None:
    rows = rows_for(perfect(), ["N1"], model="m1") + rows_for(ScriptedModelClient(text_response()), ["N1"], model="m2")
    models = summarize(rows)["models"]
    assert models["m1"]["accepted"] == 1 and models["m2"]["rejected"] == 1


@pytest.mark.parametrize(("value", "expected"), [
    ({"value": "10.00", "currency_code": "USD"}, ClaimClass.CORRECT),
    ({"currency_code": "USD", "value": "10.0"}, ClaimClass.CORRECT),
    ({"value": "10.000", "currency_code": "USD"}, ClaimClass.WRONG_VALUE),  # not listed: no normalisation
    ({"value": "10.00", "currency_code": "usd"}, ClaimClass.WRONG_VALUE),
])
def test_classification_is_exact_json_membership(value: Any, expected: ClaimClass) -> None:
    assert classify(SCENARIOS["N1"], Claim(type="amount", value=value, source="paypal")) is expected


def test_boolean_is_not_confused_with_integer() -> None:
    assert classify(SCENARIOS["N1"], Claim(type="seller_protection", value=1, source="paypal")) is ClaimClass.WRONG_VALUE


def test_shown_values_are_cleaned_and_cut() -> None:
    assert shown("a‮b​c\x07d") == "abcd"
    assert shown("x" * 300).endswith("...") and len(shown("x" * 300)) == 203
    assert shown({"b": 1, "a": 2}) == '{"a": 2, "b": 1}'


def test_rows_hold_no_prompt_or_buyer_text() -> None:
    client = perfect()
    rows = rows_for(client, ["I1", "I3", "H1"])
    text = json.dumps(rows)
    assert "SIMULATED buyer message" not in text
    assert "SYSTEM OVERRIDE" not in text
    assert client.requests[0].system[:40] not in text
