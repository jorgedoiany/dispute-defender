"""Part B: offline fault injection into SIMULATED scenarios (T-007, ADR-011). Free and deterministic.

Each scenario's correct claims (the first accepted value of every `expect` type) are
altered one fault at a time and run through the real pipeline:
  - claim layer: `verify_claims`, then `render_notes` / `prepare_send`
  - tool-input layer: `draft_claims` with a scripted client returning a faulty tool call
A fault is caught when its claim is FLAGGED or BLOCKED (claim layer) or the output is
rejected with `DraftRejected` (tool layer).

Expectations:
  catch                 the verifier should catch it
  expected_miss         outside the verifier's reach by design (the merchant record itself
                        is wrong); reported as an expected miss
  benign                an equivalent correct value; it should be VERIFIED (false-rejection check)
  by_design_rejection   a correct local date near midnight; BLOCKED by the UTC rule (ADR-008)

The faults were written with knowledge of the verifier's rules, so a high catch rate is
expected by construction.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from dispute_defender.claims import Claim, MerchantOrderRecord, Verdict
from dispute_defender.drafter import DraftRejected, ModelResponse, draft_claims

from .fake import ScriptedModelClient, text_response, tool_response
from .pipeline import run_pipeline
from .scenarios import Scenario, TruthKind
from .scoring import shown

CATCH = "catch"
EXPECTED_MISS = "expected_miss"
BENIGN = "benign"
BY_DESIGN = "by_design_rejection"

CLAIM_GROUPS = ("amount", "date", "transaction_id", "tracking_carrier", "seller_protection",
                "source_type", "merchant_record")
FAULT_MODEL_ID = "scripted-fault-model"


@dataclass(frozen=True)
class FaultCase:
    group: str
    name: str
    target: str
    expectation: str
    claims: tuple[Claim, ...]
    target_index: int
    record: MerchantOrderRecord | None


def _change_last(text: str) -> str:
    last = text[-1]
    if last.isdigit():
        return text[:-1] + str((int(last) + 1) % 10)
    # A different letter even ignoring case, so the fault is never a mere case variant.
    return text[:-1] + ("Q" if last.casefold() != "q" else "Z")


def _other_source(source: str | None) -> str:
    return "merchant_record" if source == "paypal" else "paypal"


def claim_layer_cases(scenario: Scenario) -> list[FaultCase]:
    base = scenario.base_claims()
    index = {c.type: i for i, c in enumerate(base)}
    record = scenario.record
    cases: list[FaultCase] = []

    def replace(group: str, name: str, target: str, value: Any, expectation: str = CATCH,
                source: Any = ..., rec: MerchantOrderRecord | None = record) -> None:
        i = index[target]
        old = base[i]
        new = Claim(type=old.type, value=value, source=old.source if source is ... else source)
        claims = tuple(new if j == i else c for j, c in enumerate(base))
        cases.append(FaultCase(group, name, target, expectation, claims, i, rec))

    def append(group: str, name: str, claim: Claim) -> None:
        cases.append(FaultCase(group, name, claim.type, CATCH, (*base, claim), len(base), record))

    injected = scenario.injected_values or {}

    if "amount" in index:
        v = base[index["amount"]].value
        raw, cur = v["value"], v["currency_code"]
        d = Decimal(raw)
        replace("amount", "value +0.01", "amount", {**v, "value": str(d + Decimal("0.01"))})
        replace("amount", "value x10 (decimal point shifted)", "amount", {**v, "value": str(d * 10)})
        replace("amount", "currency swapped", "amount", {**v, "currency_code": "EUR" if cur != "EUR" else "USD"})
        for label, bad in (
            ("comma decimal", {**v, "value": raw.replace(".", ",") if "." in raw else raw + ",00"}),
            ("currency symbol", {**v, "value": "$" + raw}),
            ("negative", {**v, "value": "-" + raw}),
            ("exponent", {**v, "value": "1e1"}),
            ("number instead of string", {**v, "value": float(d)}),
            ("missing currency key", {"value": raw}),
        ):
            replace("amount", f"malformed: {label}", "amount", bad)
        if "amount" in injected:
            replace("amount", "value from the buyer-message injection", "amount", injected["amount"])
        benign = raw + "0" if "." in raw else raw + ".000"
        replace("benign_variant", "amount with an extra trailing zero", "amount", {**v, "value": benign}, BENIGN)

    if "transaction_date" in index:
        v = base[index["transaction_date"]].value
        day = date.fromisoformat(v)
        replace("date", "one day later", "transaction_date", (day + timedelta(days=1)).isoformat())
        replace("date", "one day earlier", "transaction_date", (day - timedelta(days=1)).isoformat())
        replace("date", "malformed: MM/DD/YYYY", "transaction_date", day.strftime("%m/%d/%Y"))
        replace("date", "malformed: impossible date", "transaction_date", f"{day.year}-02-30")
        replace("date", "malformed: date-time", "transaction_date", f"{v}T00:00:00Z")
        if scenario.local_date:
            replace("local_date", "correct local date instead of UTC date", "transaction_date",
                    scenario.local_date, BY_DESIGN)

    if "transaction_id" in index:
        v = base[index["transaction_id"]].value
        replace("transaction_id", "one character changed", "transaction_id", _change_last(v))
        replace("transaction_id", "lower-cased", "transaction_id", v.lower())
        replace("transaction_id", "trailing space", "transaction_id", v + " ")
        if "transaction_id" in injected:
            replace("transaction_id", "value from the buyer-message injection", "transaction_id",
                    injected["transaction_id"])

    if "seller_protection" in index:
        v = base[index["seller_protection"]].value
        replace("seller_protection", "flipped", "seller_protection", not v)
        replace("seller_protection", "string instead of boolean", "seller_protection", "true" if v else "false")
        if "seller_protection" in injected:
            replace("seller_protection", "value from the buyer-message injection", "seller_protection",
                    injected["seller_protection"])

    if "tracking_number" in index:
        v = base[index["tracking_number"]].value
        replace("tracking_carrier", "tracking: one character changed", "tracking_number", _change_last(v))
        replace("tracking_carrier", "tracking: trailing space", "tracking_number", v + " ")
        if "tracking_number" in injected:
            replace("tracking_carrier", "tracking: value from the buyer-message injection", "tracking_number",
                    injected["tracking_number"])
        if record is not None:
            altered = _change_last(v)
            replace("merchant_record", "record tracking number itself wrong (claim copies it)", "tracking_number",
                    altered, EXPECTED_MISS, rec=record.model_copy(update={"tracking_number": altered}))

    if "carrier" in index:
        v = base[index["carrier"]].value
        other = "UPS" if v.casefold() != "ups" else "FEDEX"
        replace("tracking_carrier", "carrier: a different carrier", "carrier", other)
        if "carrier" in injected:
            replace("tracking_carrier", "carrier: value from the buyer-message injection", "carrier",
                    injected["carrier"])
        if record is not None:
            replace("merchant_record", "record carrier itself wrong (claim copies it)", "carrier", other,
                    EXPECTED_MISS, rec=record.model_copy(update={"carrier": other}))
        for label, variant in (("upper case", v.upper()), ("lower case", v.lower()), ("surrounding spaces", f" {v} ")):
            if variant != v:
                replace("benign_variant", f"carrier in {label}", "carrier", variant, BENIGN)

    for claim in base:
        replace("source_type", f"{claim.type}: wrong source", claim.type, claim.value,
                source=_other_source(claim.source))
        replace("source_type", f"{claim.type}: no source", claim.type, claim.value, source=None)
    append("source_type", "unknown claim type", Claim(type="delivery_date", value="2026-11-12", source="merchant_record"))
    first = base[0]
    dup_value: Any = (_change_last(first.value) if isinstance(first.value, str)
                      else {**first.value, "value": "1.00"} if isinstance(first.value, dict) else not first.value)
    append("source_type", "duplicate claim with a different value", Claim(type=first.type, value=dup_value,
                                                                           source=first.source))
    return cases


def _outcome(expectation: str, caught: bool) -> str:
    if expectation == CATCH:
        return "caught" if caught else "missed"
    if expectation == EXPECTED_MISS:
        return "caught" if caught else "expected_miss"
    if expectation == BENIGN:
        return "wrongly_rejected" if caught else "verified"
    return "rejected_by_design" if caught else "verified"


def run_claim_layer(scenarios: Iterable[Scenario]) -> list[dict[str, Any]]:
    rows = []
    for scenario in scenarios:
        for case in claim_layer_cases(scenario):
            result = run_pipeline(scenario.dispute, case.claims, case.record)
            target = result.results[case.target_index]
            caught = target.verdict is not Verdict.VERIFIED
            rows.append({
                "scenario_id": scenario.id, "layer": "claim", "group": case.group, "fault": case.name,
                "target": case.target, "expectation": case.expectation, "verdict": target.verdict.value,
                "caught": caught, "outcome": _outcome(case.expectation, caught),
                "reached_send": not caught and result.send.sent, "reason": shown(target.reason),
            })
    return rows


def _tool_input(scenario: Scenario) -> list[dict[str, Any]]:
    return [{"type": c.type, "source": c.source, "value": c.value} for c in scenario.base_claims()]


def tool_layer_cases(scenario: Scenario) -> list[tuple[str, ModelResponse]]:
    claims = _tool_input(scenario)
    first = claims[0]
    bad_type: Any = 12345 if isinstance(first["value"], str) else "true" if isinstance(first["value"], bool) else "10.00"

    def with_first(change: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        return {"claims": [change(dict(first)), *claims[1:]]}

    return [
        ("wrong source for the claim type", tool_response(with_first(lambda c: {**c, "source": _other_source(c["source"])}))),
        ("unknown claim type", tool_response({"claims": [*claims, {"type": "delivery_date", "source": "merchant_record",
                                                                   "value": "2026-11-12"}]})),
        ("extra field", tool_response(with_first(lambda c: {**c, "confidence": 0.9}))),
        ("wrong JSON type for the value", tool_response(with_first(lambda c: {**c, "value": bad_type}))),
        ("missing value", tool_response(with_first(lambda c: {k: v for k, v in c.items() if k != "value"}))),
        ("empty claims list", tool_response({"claims": []})),
        ("more than 20 claims", tool_response({"claims": [first] * 21})),
        ("input is not an object", tool_response([first])),
        ("two tool calls", tool_response({"claims": claims}, uses=2)),
        ("another tool name", tool_response({"claims": claims}, name="send_response")),
        ("text only, no tool call", text_response()),
        ("stopped at max_tokens", tool_response({"claims": claims}, stop="max_tokens")),
    ]


def run_tool_layer(scenarios: Iterable[Scenario]) -> list[dict[str, Any]]:
    rows = []
    for scenario in scenarios:
        for name, response in tool_layer_cases(scenario):
            try:
                draft_claims(scenario.dispute, scenario.record, client=ScriptedModelClient(response),
                             model_id=FAULT_MODEL_ID)
            except DraftRejected:
                caught = True
            else:
                caught = False
            rows.append({"scenario_id": scenario.id, "layer": "tool_input", "group": "tool_input", "fault": name,
                         "target": None, "expectation": CATCH, "verdict": None, "caught": caught,
                         "outcome": "caught" if caught else "missed", "reached_send": False, "reason": None})
    return rows


def baseline(scenarios: Iterable[Scenario]) -> dict[str, int]:
    """Correct claims with no fault: how many the verifier wrongly rejects."""
    total = rejected = 0
    for scenario in scenarios:
        result = run_pipeline(scenario.dispute, scenario.base_claims(), scenario.record)
        total += len(result.results)
        rejected += sum(r.verdict is not Verdict.VERIFIED for r in result.results)
    return {"correct_claims": total, "wrongly_rejected": rejected}


def summarize_faults(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Per group: applied and a count per outcome."""
    table: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        counts = table[row["group"]]
        counts["applied"] += 1
        counts[row["outcome"]] += 1
        counts["reached_send"] += row["reached_send"]
    return {group: dict(counts) for group, counts in table.items()}


def run_faults(scenarios: list[Scenario]) -> dict[str, Any]:
    rows = run_claim_layer(scenarios) + run_tool_layer(scenarios)
    return {
        "simulated": True,
        "notice": "SIMULATED scenarios; offline fault injection (T-007 Part B). Not real-world accuracy.",
        "scenario_count": len(scenarios),
        "baseline": baseline(scenarios),
        "summary": summarize_faults(rows),
        "rows": rows,
    }
