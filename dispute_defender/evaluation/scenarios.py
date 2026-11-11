"""Load the SIMULATED evaluation scenarios (T-007, ADR-011).

Each file in `evaluation/scenarios/` describes one simulated dispute: a PayPal-shaped
dispute body (parsed with the app's own `Dispute` model, so it passes the same boundary
validation as live data), an optional merchant record, and a hand-written ground truth
for every claim type. A file without `"simulated": true` is refused.

Ground truth per claim type, one of:
  {"expect": [v1, v2, ...]}   accepted values, compared as exact JSON (no normalisation)
  {"absent": true}            the fact is missing; the claim must not be made
  {"unsupported": true}       the model may make the claim; it must not be VERIFIED or sent
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from dispute_defender.claims import SUPPORTED_CLAIM_TYPES, Claim, MerchantOrderRecord
from dispute_defender.drafter import DRAFT_CLAIM_SOURCES
from dispute_defender.paypal import Dispute

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = REPO_ROOT / "evaluation"
SCENARIO_DIR = EVAL_DIR / "scenarios"

CATEGORIES = (
    "normal", "transactions", "seller_protection", "amount_currency", "date_timezone",
    "merchant_record", "carrier", "prompt_injection", "hostile_characters",
)
SEND_OUTCOMES = ("send", "refuse")


class ScenarioError(ValueError):
    """A scenario file is malformed or not labelled as simulated."""


class TruthKind(StrEnum):
    EXPECT = "expect"
    ABSENT = "absent"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class TypeTruth:
    kind: TruthKind
    accepted: tuple[Any, ...] = ()


@dataclass(frozen=True)
class Scenario:
    id: str
    category: str
    description: str
    dispute: Dispute
    record: MerchantOrderRecord | None
    truth: dict[str, TypeTruth]
    expected_send: str
    local_date: str | None = None
    injected_values: dict[str, Any] | None = None

    def base_claims(self) -> list[Claim]:
        """One correct claim per `expect` type (its first accepted value), in a fixed order."""
        return [
            Claim(type=t, value=truth.accepted[0], source=DRAFT_CLAIM_SOURCES[t])
            for t, truth in sorted(self.truth.items())
            if truth.kind is TruthKind.EXPECT
        ]


def _truth(sid: str, claim_type: str, raw: Any) -> TypeTruth:
    if not isinstance(raw, dict) or len(raw) != 1:
        raise ScenarioError(f"{sid}: ground truth for {claim_type} must have exactly one key")
    ((key, value),) = raw.items()
    if key == "expect":
        if not isinstance(value, list) or not value:
            raise ScenarioError(f"{sid}: {claim_type}.expect must be a non-empty list")
        return TypeTruth(TruthKind.EXPECT, tuple(value))
    if key in ("absent", "unsupported") and value is True:
        return TypeTruth(TruthKind(key))
    raise ScenarioError(f"{sid}: unknown ground truth for {claim_type}")


def parse_scenario(doc: Any, *, name: str = "<scenario>") -> Scenario:
    if not isinstance(doc, dict) or doc.get("simulated") is not True:
        raise ScenarioError(f"{name}: not labelled as simulated")
    sid = doc.get("id")
    if not isinstance(sid, str) or not sid:
        raise ScenarioError(f"{name}: missing id")
    if doc.get("category") not in CATEGORIES:
        raise ScenarioError(f"{sid}: unknown category")
    if doc.get("expected_send") not in SEND_OUTCOMES:
        raise ScenarioError(f"{sid}: expected_send must be 'send' or 'refuse'")
    truth_raw = doc.get("ground_truth")
    if not isinstance(truth_raw, dict) or set(truth_raw) != set(SUPPORTED_CLAIM_TYPES):
        raise ScenarioError(f"{sid}: ground truth must cover exactly the claim types {sorted(SUPPORTED_CLAIM_TYPES)}")
    record_raw = doc.get("merchant_record")
    return Scenario(
        id=sid,
        category=doc["category"],
        description=str(doc.get("description", "")),
        dispute=Dispute.model_validate(doc.get("dispute")),
        record=None if record_raw is None else MerchantOrderRecord.model_validate(record_raw),
        truth={t: _truth(sid, t, v) for t, v in truth_raw.items()},
        expected_send=doc["expected_send"],
        local_date=doc.get("local_date"),
        injected_values=doc.get("injected_values"),
    )


def scenario_files(directory: Path = SCENARIO_DIR) -> list[Path]:
    return sorted(directory.glob("*.json"))


def load_scenarios(directory: Path = SCENARIO_DIR, ids: list[str] | None = None) -> list[Scenario]:
    scenarios = [parse_scenario(json.loads(p.read_text(encoding="utf-8")), name=p.name)
                 for p in scenario_files(directory)]
    seen = [s.id for s in scenarios]
    if len(seen) != len(set(seen)):
        raise ScenarioError("duplicate scenario id")
    if ids:
        unknown = sorted(set(ids) - set(seen))
        if unknown:
            raise ScenarioError(f"unknown scenario id(s): {', '.join(unknown)}")
        scenarios = [s for s in scenarios if s.id in ids]
    return scenarios
