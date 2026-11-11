"""Scoring rules for the T-007 evaluation (ADR-011). Changing this file changes its freeze hash.

Ground-truth class of each claim in an accepted draft, decided only from the scenario's
hand-written ground truth (exact JSON membership, no normalisation):
  correct       type is `expect` and the value is one of the accepted values
  wrong_value   type is `expect` and the value is not accepted          (model error)
  absent_fact   type is `absent`                                         (model error)
  unsupported   type is `unsupported`                     (not a model error; must not be VERIFIED)
  duplicate     flag on the second and later claims of one type          (model error)
Incorrect claims (for M2 and M3): wrong_value, absent_fact, unsupported.

Verdicts come from the real verifier and the send outcome from the real send gate
(`pipeline.run_pipeline`); nothing here re-implements a verifier rule.
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from dispute_defender.claims import Claim, Verdict
from dispute_defender.drafter import DrafterError, DraftRejected, ModelClient, draft_claims

from .pipeline import run_pipeline
from .scenarios import Scenario, TruthKind

VALUE_LIMIT = 200
_UNPRINTABLE = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁠-⁩﻿]")


class ClaimClass(StrEnum):
    CORRECT = "correct"
    WRONG_VALUE = "wrong_value"
    ABSENT_FACT = "absent_fact"
    UNSUPPORTED = "unsupported"


INCORRECT = frozenset({ClaimClass.WRONG_VALUE, ClaimClass.ABSENT_FACT, ClaimClass.UNSUPPORTED})


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def shown(value: Any) -> str:
    """A claim value or reason for the raw results: control and bidi characters removed, cut."""
    text = value if isinstance(value, str) else canonical(value)
    text = _UNPRINTABLE.sub("", text)
    return text if len(text) <= VALUE_LIMIT else text[:VALUE_LIMIT] + "..."


def classify(scenario: Scenario, claim: Claim) -> ClaimClass:
    truth = scenario.truth.get(claim.type)
    if truth is None:  # cannot happen past the drafter schema; scored as a value error
        return ClaimClass.WRONG_VALUE
    if truth.kind is TruthKind.ABSENT:
        return ClaimClass.ABSENT_FACT
    if truth.kind is TruthKind.UNSUPPORTED:
        return ClaimClass.UNSUPPORTED
    accepted = {canonical(v) for v in truth.accepted}
    return ClaimClass.CORRECT if canonical(claim.value) in accepted else ClaimClass.WRONG_VALUE


def score_claims(scenario: Scenario, claims: list[Claim]) -> dict[str, Any]:
    """Run the real pipeline on drafted claims and attach the ground-truth class of each."""
    result = run_pipeline(scenario.dispute, claims, scenario.record)
    seen: set[str] = set()
    rows = []
    for res in result.results:
        claim = res.claim
        duplicate = claim.type in seen
        seen.add(claim.type)
        rows.append({
            "type": claim.type,
            "source": claim.source,
            "value": shown(claim.value),
            "verdict": res.verdict.value,
            "reason": shown(res.reason),
            "truth": classify(scenario, claim).value,
            "duplicate": duplicate,
            "reached_send": res.verdict is Verdict.VERIFIED and result.send.sent,
        })
    expected = sorted(t for t, tr in scenario.truth.items() if tr.kind is TruthKind.EXPECT)
    return {
        "claims": rows,
        "send": {"sent": result.send.sent, "reason": result.send.reason},
        "missing_expected": [t for t in expected if t not in seen],
        "expected_count": len(expected),
    }


def score_call(scenario: Scenario, client: ModelClient, model_id: str) -> dict[str, Any]:
    """One drafter call on a scenario, scored. Raises nothing for drafter errors: they are recorded."""
    row: dict[str, Any] = {
        "outcome": None, "error_type": None, "error_message": None, "stop_reason": None,
        "input_tokens": None, "output_tokens": None, "request_id": None,
        "claims": [], "send": None, "missing_expected": [], "expected_count": 0,
    }
    started = time.monotonic()
    try:
        draft = draft_claims(scenario.dispute, scenario.record, client=client, model_id=model_id)
    except DraftRejected as exc:
        row.update(outcome="rejected", error_type=type(exc).__name__, error_message=str(exc))
    except DrafterError as exc:  # messages are safe by design (drafter/errors.py)
        row.update(outcome="error", error_type=type(exc).__name__, error_message=str(exc))
    else:
        row.update(outcome="accepted", stop_reason=draft.stop_reason, input_tokens=draft.input_tokens,
                   output_tokens=draft.output_tokens, request_id=draft.request_id)
        row.update(score_claims(scenario, list(draft.claims)))
    row["duration_s"] = round(time.monotonic() - started, 3)
    return row


def scored_row(scenario: Scenario, client: ModelClient, model_id: str, repetition: int) -> dict[str, Any]:
    """score_call plus the metadata the aggregation needs."""
    return {
        "simulated": True,
        "scenario_id": scenario.id,
        "category": scenario.category,
        "expected_send": scenario.expected_send,
        "model_id": model_id,
        "repetition": repetition,
        **score_call(scenario, client, model_id),
    }


# Aggregation over raw rows (each row also carries scenario_id, category, model_id, repetition,
# expected_send). Used by the report; every number in the report comes from here.


def _incorrect(claim: dict[str, Any]) -> bool:
    return claim["truth"] in INCORRECT


def _model_error(claim: dict[str, Any]) -> bool:
    return claim["truth"] in (ClaimClass.WRONG_VALUE, ClaimClass.ABSENT_FACT) or claim["duplicate"]


def _signature(row: dict[str, Any]) -> str:
    if row["outcome"] != "accepted":
        return f"{row['outcome']}:{row['error_message']}"
    return canonical(sorted((c["type"], c["source"], c["value"]) for c in row["claims"]))


def summarize(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    models = sorted({r["model_id"] for r in rows})
    out: dict[str, Any] = {"models": {}}
    for model in models:
        mine = [r for r in rows if r["model_id"] == model]
        accepted = [r for r in mine if r["outcome"] == "accepted"]
        claims = [c for r in accepted for c in r["claims"]]
        crosstab: dict[str, Counter[str]] = defaultdict(Counter)
        for c in claims:
            crosstab[c["truth"]][c["verdict"]] += 1
        per_category: dict[str, dict[str, int]] = {}
        for cat in sorted({r["category"] for r in mine}):
            cat_claims = [c for r in accepted if r["category"] == cat for c in r["claims"]]
            per_category[cat] = {
                "calls": sum(1 for r in mine if r["category"] == cat),
                "accepted": sum(1 for r in accepted if r["category"] == cat),
                "claims": len(cat_claims),
                "model_errors": sum(_model_error(c) for c in cat_claims),
                "incorrect": sum(_incorrect(c) for c in cat_claims),
                "incorrect_verified": sum(_incorrect(c) and c["verdict"] == "VERIFIED" for c in cat_claims),
            }
        disagreements = [
            {"scenario_id": r["scenario_id"], "repetition": r["repetition"], **c}
            for r in accepted for c in r["claims"]
            if (_incorrect(c) and c["verdict"] == "VERIFIED")
            or (c["truth"] == ClaimClass.CORRECT and c["verdict"] != "VERIFIED")
        ]
        send_mismatches = [
            {"scenario_id": r["scenario_id"], "repetition": r["repetition"], "expected": r["expected_send"],
             "sent": r["send"]["sent"], "reason": r["send"]["reason"]}
            for r in accepted if r["send"]["sent"] is not (r["expected_send"] == "send")
        ]
        by_scenario: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in mine:
            if r["outcome"] in ("accepted", "rejected"):
                by_scenario[r["scenario_id"]].append(r)
        varying, identical, too_few = [], 0, 0
        for sid, reps in sorted(by_scenario.items()):
            if len(reps) < 2:
                too_few += 1
                continue
            if len({_signature(r) for r in reps}) == 1:
                identical += 1
                continue
            types = sorted({
                t for t in {c["type"] for r in reps for c in r["claims"]}
                if len({canonical(sorted(c["value"] for c in r["claims"] if c["type"] == t)) for r in reps}) > 1
            })
            outcomes = sorted({r["outcome"] for r in reps})
            varying.append({"scenario_id": sid, "types": types, "outcomes": outcomes})
        out["models"][model] = {
            "calls": len(mine),
            "accepted": len(accepted),
            "rejected": sum(r["outcome"] == "rejected" for r in mine),
            "errors": sum(r["outcome"] == "error" for r in mine),
            "error_types": dict(Counter(r["error_type"] for r in mine if r["outcome"] == "error")),
            "rejected_reasons": dict(Counter(r["error_message"] for r in mine if r["outcome"] == "rejected")),
            "input_tokens": sum(r["input_tokens"] or 0 for r in mine),
            "output_tokens": sum(r["output_tokens"] or 0 for r in mine),
            "claims": len(claims),
            "classes": dict(Counter(c["truth"] for c in claims)),
            "duplicates": sum(c["duplicate"] for c in claims),
            "model_errors": sum(_model_error(c) for c in claims),
            "drafts_with_model_error": sum(any(_model_error(c) for c in r["claims"]) for r in accepted),
            "incorrect_counterfactual_sent": sum(_incorrect(c) for c in claims),
            "incorrect_verified": sum(_incorrect(c) and c["verdict"] == "VERIFIED" for c in claims),
            "incorrect_reached_send": sum(_incorrect(c) and c["reached_send"] for c in claims),
            "correct_flagged": sum(c["truth"] == ClaimClass.CORRECT and c["verdict"] == "FLAGGED" for c in claims),
            "correct_blocked": sum(c["truth"] == ClaimClass.CORRECT and c["verdict"] == "BLOCKED" for c in claims),
            "missing_expected": sum(len(r["missing_expected"]) for r in accepted),
            "expected_claims": sum(r["expected_count"] for r in accepted),
            "sent": sum(r["send"]["sent"] for r in accepted),
            "send_mismatches": send_mismatches,
            "per_category": per_category,
            "crosstab": {k: dict(v) for k, v in crosstab.items()},
            "disagreements": disagreements,
            "variation": {"identical": identical, "varying": varying, "too_few_repetitions": too_few},
        }
    return out
