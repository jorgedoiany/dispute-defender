"""Local stand-in for the Bedrock model client in replay mode (T-010, ADR-012). No network.

`converse` answers the request the real drafter built with the replay dispute's model
output, found by the `seller_transaction_id` in the prompt's <paypal_data> block. The
output is returned as a `submit_claims` tool call, so the real `validate_response()`,
`DraftOutput` schema and verifier all run on it. It never falls back to another output.
"""
from __future__ import annotations

import copy
import json
import re

from dispute_defender.drafter import TOOL_NAME, DrafterError, ModelRequest, ModelResponse, ToolUse

from .data import ReplayData, load_replay

_PAYPAL_DATA = re.compile(r"<paypal_data>\n(.*?)\n</paypal_data>", re.DOTALL)
REPLAY_REQUEST_ID = "replay"


class ReplayModelError(DrafterError):
    """No replay output for this request. The message names no prompt content."""


def replay_model_label(data: ReplayData) -> str:
    return f"replay of {data.recorded_model_id} (recorded 2026-11-11 on simulated scenarios)"


class ReplayModelClient:
    def __init__(self, data: ReplayData | None = None) -> None:
        self.data = data or load_replay()
        self._outputs = {
            d.transaction_id: d.model_output for d in self.data.disputes if d.model_output is not None
        }
        self.requests: list[ModelRequest] = []

    def converse(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if request.tool_name != TOOL_NAME:
            raise ReplayModelError("replay model client only answers the submit_claims tool")
        match = _PAYPAL_DATA.search(request.user_text)
        try:
            txn = json.loads(match.group(1))["transaction"]["seller_transaction_id"] if match else None
        except (ValueError, KeyError, TypeError):
            txn = None
        output = self._outputs.get(txn) if isinstance(txn, str) else None
        if output is None:
            raise ReplayModelError("no replay model output for this dispute")
        return ModelResponse(
            stop_reason="tool_use",
            tool_uses=(ToolUse(name=TOOL_NAME, input=copy.deepcopy(output)),),
            request_id=REPLAY_REQUEST_ID,
        )
