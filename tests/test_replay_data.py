"""Replay data: provenance and hygiene (T-010, ADR-012). Offline."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from dispute_defender.replay import DATA_PATH, load_replay

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "evaluation" / "results" / "raw-2026-11-11.jsonl"
SCENARIOS = ROOT / "evaluation" / "scenarios"

# Real sandbox IDs used in T-002 to T-006 (see PROGRESS.md and tests/fixtures/paypal).
REAL_IDS = (
    "PP-R-HBV", "PP-R-KXL", "PP-R-UXH", "10197617", "10197854", "10198605", "54X87564PT289050U",
)
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def raw_text() -> str:
    return DATA_PATH.read_text(encoding="utf-8")


def scenario(sid: str) -> dict[str, Any]:
    return json.loads((SCENARIOS / f"{sid}.json").read_text())


def recorded_claims(sid: str) -> list[dict[str, Any]]:
    """The recorded claims of the primary model, repetition 1, rebuilt to tool-input shape."""
    rows = [json.loads(line) for line in RAW.read_text().splitlines() if line.strip()]
    (row,) = [r for r in rows if r["scenario_id"] == sid and r["model_label"] == "primary"
              and r["repetition"] == 1]
    out = []
    for c in row["claims"]:
        value: Any = c["value"]
        if c["type"] == "amount":
            value = json.loads(value)
        elif c["type"] == "seller_protection":
            value = {"true": True, "false": False}[value]
        out.append({"type": c["type"], "source": c["source"], "value": value})
    return out


def test_loads_and_is_labelled_simulated() -> None:
    data = load_replay()
    assert data.simulated is True
    assert "SIMULATED" in data.notice and "Not real PayPal data" in data.notice
    assert [d.dispute_id for d in data.disputes] == ["PP-R-SIM-N1", "PP-R-SIM-REPLAY2", "PP-R-SIM-REPLAY3"]
    for d in data.disputes:
        assert d.source.dispute.startswith("SIMULATED")
        assert "Not a real PayPal dispute" in d.source.dispute


def test_dispute_1_is_scenario_n1_with_its_recorded_output() -> None:
    d = load_replay().by_id("PP-R-SIM-N1")
    assert d is not None
    assert d.dispute == scenario("N1")["dispute"]
    assert d.model_output == {"claims": recorded_claims("N1")}
    assert d.source.model_output and d.source.model_output.startswith("RECORDED")
    assert d.source.adapted is None and d.source.injected is None


def test_dispute_2_is_not_sendable_and_has_no_model_output() -> None:
    d = load_replay().by_id("PP-R-SIM-REPLAY2")
    assert d is not None
    assert d.dispute["status"] == "WAITING_FOR_BUYER_RESPONSE"
    assert [link["rel"] for link in d.dispute["links"]] == ["self"]
    assert d.model_output is None and d.source.model_output is None


def test_dispute_3_differs_from_the_n2_recording_only_where_declared() -> None:
    d = load_replay().by_id("PP-R-SIM-REPLAY3")
    assert d is not None and d.model_output is not None
    expected = copy.deepcopy(recorded_claims("N2"))
    for c in expected:
        if c["type"] == "transaction_id":
            c["value"] = "SIMRP3TXN00000001"  # adapted, declared in source.adapted
        if c["type"] == "amount":
            c["value"] = {"value": "250.00", "currency_code": "USD"}  # injected, declared in source.injected
    assert d.model_output == {"claims": expected}
    assert d.source.adapted and "SIMRP3TXN00000001" in d.source.adapted
    assert d.source.injected and d.source.injected.startswith(
        "SIMULATED model error injected to demonstrate the verifier")
    txn = d.dispute["disputed_transactions"][0]
    assert txn["seller_transaction_id"] == "SIMRP3TXN00000001"
    assert "seller_protection_eligible" not in txn
    n2 = scenario("N2")["dispute"]["disputed_transactions"][0]
    assert txn["gross_amount"] == n2["gross_amount"] and txn["create_time"] == n2["create_time"]


def test_after_send_state_is_under_review_without_provide_evidence() -> None:
    for d in load_replay().disputes:
        assert d.after_send == {"status": "UNDER_REVIEW", "links": [l for l in d.dispute["links"]
                                                                     if l["rel"] == "self"]}


def test_no_real_ids_request_ids_or_personal_data() -> None:
    text = raw_text()
    for real in REAL_IDS:
        assert real not in text
    assert not UUID.search(text)
    assert "request_id" not in text
    emails = set(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text))
    assert emails == {"fake-buyer@example.invalid"}
    names = set(re.findall(r'"name": "([^"]*)"', text))
    assert names <= {"FAKE-BUYER-NAME", "Simulated Test Store"}
    assert not re.search(r"AKIA[0-9A-Z]{16}|aws_secret|client_secret|access_token", text, re.I)


@pytest.mark.parametrize("change, message", [
    (lambda d: d.update(simulated=False), "simulated"),
    (lambda d: d["disputes"][0]["source"].update(dispute=""), "dispute"),
    (lambda d: d["disputes"][0]["source"].update(model_output=None), "source label"),
    (lambda d: d["disputes"][1]["dispute"].update(dispute_id=d["disputes"][0]["dispute"]["dispute_id"]),
     "duplicate dispute"),
    (lambda d: d["disputes"][0]["model_output"]["claims"][0].update(source="merchant_record"), "claims"),
    (lambda d: d["disputes"][0]["dispute"].update(dispute_id="bad/id"), "dispute_id"),
])
def test_loader_refuses_bad_data(tmp_path: Path, change: Any, message: str) -> None:
    data = json.loads(raw_text())
    change(data)
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=message):
        load_replay(path)
