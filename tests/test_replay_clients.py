"""Replay PayPal and model clients (T-010, ADR-012). Offline, no web layer."""
from __future__ import annotations

import pytest

from dispute_defender.claims import MerchantOrderRecord, Verdict, verify_claims
from dispute_defender.drafter import DraftRejected, ModelRequest, draft_claims
from dispute_defender.paypal import ActionAck, Dispute, Evidence, PayPalAPIError, TrackingInfo
from dispute_defender.replay import ReplayModelClient, ReplayModelError, ReplayPayPalClient, load_replay

MODEL_LABEL = "replay"


def evidence() -> Evidence:
    return Evidence(tracking_info=[TrackingInfo(carrier_name="FEDEX", tracking_number="SIM100000001")],
                    notes="Replay test notes.")


def test_list_and_get_go_through_the_app_models() -> None:
    client = ReplayPayPalClient()
    items = client.list_disputes()
    assert [i.dispute_id for i in items] == ["PP-R-SIM-N1", "PP-R-SIM-REPLAY2", "PP-R-SIM-REPLAY3"]
    dispute = client.get_dispute("PP-R-SIM-N1")
    assert isinstance(dispute, Dispute) and dispute.has_link("provide_evidence")
    assert not client.get_dispute("PP-R-SIM-REPLAY2").has_link("provide_evidence")
    assert client.list_disputes(page_size=1)[0].dispute_id == "PP-R-SIM-N1"


def test_unknown_or_bad_id() -> None:
    client = ReplayPayPalClient()
    with pytest.raises(PayPalAPIError) as exc:
        client.get_dispute("PP-R-NOPE")
    assert exc.value.http_status == 404
    with pytest.raises(ValueError):
        client.get_dispute("../x")


def test_provide_evidence_records_payload_and_switches_state() -> None:
    client = ReplayPayPalClient()
    ack = client.provide_evidence("PP-R-SIM-N1", [evidence()])
    assert isinstance(ack, ActionAck)
    assert client.sent["PP-R-SIM-N1"] == [[evidence().to_payload()]]
    after = client.get_dispute("PP-R-SIM-N1")
    assert after.status == "UNDER_REVIEW" and after.link_names() == ["self"]
    with pytest.raises(PayPalAPIError) as exc:  # no link any more: refused like PayPal does
        client.provide_evidence("PP-R-SIM-N1", [evidence()])
    assert exc.value.http_status == 422
    assert len(client.sent["PP-R-SIM-N1"]) == 1


def test_provide_evidence_refused_without_link() -> None:
    client = ReplayPayPalClient()
    with pytest.raises(PayPalAPIError):
        client.provide_evidence("PP-R-SIM-REPLAY2", [evidence()])
    assert client.sent == {}


def test_state_is_per_client() -> None:
    first, second = ReplayPayPalClient(), ReplayPayPalClient()
    first.provide_evidence("PP-R-SIM-N1", [evidence()])
    assert second.get_dispute("PP-R-SIM-N1").status == "WAITING_FOR_SELLER_RESPONSE"


def test_unused_methods_fail_loudly() -> None:
    client = ReplayPayPalClient()
    with pytest.raises(NotImplementedError):
        client.get_token()
    with pytest.raises(NotImplementedError):
        client.send_message("PP-R-SIM-N1", "x")


def test_model_output_goes_through_the_real_drafter_and_verifier() -> None:
    paypal, model = ReplayPayPalClient(), ReplayModelClient()
    dispute = paypal.get_dispute("PP-R-SIM-N1")
    record = MerchantOrderRecord(tracking_number="SIM100000001", carrier="FEDEX")
    draft = draft_claims(dispute, record, client=model, model_id=MODEL_LABEL)
    assert [c.type for c in draft.claims] == [
        "transaction_id", "amount", "transaction_date", "seller_protection", "tracking_number", "carrier"]
    results = verify_claims(dispute, draft.claims, record)
    assert all(r.verdict is Verdict.VERIFIED for r in results)
    assert draft.request_id == "replay" and draft.input_tokens is None


def test_dispute_3_gives_blocked_and_flagged() -> None:
    paypal, model = ReplayPayPalClient(), ReplayModelClient()
    dispute = paypal.get_dispute("PP-R-SIM-REPLAY3")
    record = MerchantOrderRecord(tracking_number="SIM100000002", carrier="FEDEX")
    results = verify_claims(dispute, draft_claims(dispute, record, client=model, model_id=MODEL_LABEL).claims,
                            record)
    verdicts = {r.claim.type: r.verdict for r in results}
    assert verdicts == {
        "transaction_id": Verdict.VERIFIED, "amount": Verdict.BLOCKED, "transaction_date": Verdict.VERIFIED,
        "seller_protection": Verdict.FLAGGED, "tracking_number": Verdict.VERIFIED, "carrier": Verdict.VERIFIED,
    }


def test_same_answer_every_call() -> None:
    paypal, model = ReplayPayPalClient(), ReplayModelClient()
    dispute = paypal.get_dispute("PP-R-SIM-N1")
    first = draft_claims(dispute, None, client=model, model_id=MODEL_LABEL)
    second = draft_claims(dispute, None, client=model, model_id=MODEL_LABEL)
    assert first.claims == second.claims and len(model.requests) == 2


def test_model_refuses_unknown_dispute_and_other_tools() -> None:
    model = ReplayModelClient()
    paypal = ReplayPayPalClient()
    with pytest.raises(ReplayModelError):  # dispute 2 has no model output
        draft_claims(paypal.get_dispute("PP-R-SIM-REPLAY2"), None, client=model, model_id=MODEL_LABEL)
    with pytest.raises(ReplayModelError):
        model.converse(ModelRequest(model_id="x", tool_name="other", system="", user_text="", tool={}))
    with pytest.raises(ReplayModelError):
        model.converse(ModelRequest(model_id="x", tool_name="submit_claims", system="",
                                    user_text="<paypal_data>\nnot json\n</paypal_data>", tool={}))


def test_bad_replay_output_is_rejected_by_the_real_validation() -> None:
    data = load_replay()
    entry = data.disputes[0]
    broken = entry.model_copy(update={"model_output": {"claims": [{"type": "amount", "source": "paypal",
                                                                    "value": "ten"}]}})
    model = ReplayModelClient(data.model_copy(update={"disputes": [broken]}))
    dispute = ReplayPayPalClient().get_dispute("PP-R-SIM-N1")
    with pytest.raises(DraftRejected):
        draft_claims(dispute, None, client=model, model_id=MODEL_LABEL)
