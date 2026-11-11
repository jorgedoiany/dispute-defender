"""Local stand-in for PayPalClient in replay mode (T-010, ADR-012). No network.

Implements the three methods the web app calls. Every dispute goes through the app's
own pydantic models, as a real PayPal response would. `provide_evidence` keeps the
payload in memory (`sent`) and moves the dispute to its hand-written read-back state.
State lives in this object only; restarting the app resets it.
"""
from __future__ import annotations

import copy
from collections.abc import Sequence
from typing import Any

from dispute_defender.paypal import ActionAck, Dispute, DisputeListItem, Evidence, PayPalAPIError, check_dispute_id

from .data import ReplayData, ReplayDispute, load_replay

_PATH = "/v1/customer/disputes"


class ReplayPayPalClient:
    """Serves replay disputes and records evidence locally. Never sends anything."""

    def __init__(self, data: ReplayData | None = None) -> None:
        self.data = data or load_replay()
        self._state: dict[str, dict[str, Any]] = {
            d.dispute_id: copy.deepcopy(d.dispute) for d in self.data.disputes
        }
        self.sent: dict[str, list[list[dict[str, object]]]] = {}

    def _entry(self, dispute_id: str, method: str, path: str) -> ReplayDispute:
        check_dispute_id(dispute_id)
        entry = self.data.by_id(dispute_id)
        if entry is None:
            raise PayPalAPIError(method=method, path=path, http_status=404, name="RESOURCE_NOT_FOUND")
        return entry

    def list_disputes(self, page_size: int = 20) -> list[DisputeListItem]:
        return [DisputeListItem.model_validate(raw) for raw in list(self._state.values())[:page_size]]

    def get_dispute(self, dispute_id: str) -> Dispute:
        self._entry(dispute_id, "GET", f"{_PATH}/{{id}}")
        return Dispute.model_validate(self._state[dispute_id])

    def provide_evidence(self, dispute_id: str, evidences: Sequence[Evidence]) -> ActionAck:
        path = f"{_PATH}/{{id}}/provide-evidence"
        entry = self._entry(dispute_id, "POST", path)
        if not Dispute.model_validate(self._state[dispute_id]).has_link("provide_evidence"):
            raise PayPalAPIError(method="POST", path=path, http_status=422,
                                 name="UNPROCESSABLE_ENTITY",
                                 issues=["ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE"])
        payload = [Evidence.model_validate(e.model_dump()).to_payload() for e in evidences]
        self.sent.setdefault(dispute_id, []).append(payload)
        self._state[dispute_id] = {**self._state[dispute_id], **copy.deepcopy(entry.after_send)}
        return ActionAck.model_validate({"links": entry.after_send.get("links", [])})

    def source(self, dispute_id: str) -> ReplayDispute | None:
        """The replay entry for a dispute, for the page's source labels."""
        return self.data.by_id(dispute_id)

    # The web app never calls these; a real client would. Fail loudly instead of faking.
    def get_token(self) -> Any:
        raise NotImplementedError("replay mode has no PayPal token")

    def send_message(self, dispute_id: str, message: str) -> Any:
        raise NotImplementedError("replay mode does not send messages")
