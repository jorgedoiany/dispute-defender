"""Scripted model clients for offline use: Part B and tests (T-007). No model is called.

`ScriptedModelClient` answers each request with a fixed response, a callable, or raises
an exception. `copying_responder` behaves like an ideal model: it reads the allowlisted
facts out of the prompt the app built and copies every non-null value into a claim.
It is a test double, never used for the live evaluation.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from dispute_defender.drafter import TOOL_NAME, ModelRequest, ModelResponse, ToolUse

Responder = Callable[[ModelRequest], ModelResponse]
Mutator = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]

_BLOCK = r"<{tag}>\n(.*?)\n</{tag}>"


def tool_response(tool_input: Any, *, name: str = TOOL_NAME, stop: str = "tool_use",
                  uses: int = 1) -> ModelResponse:
    return ModelResponse(
        stop_reason=stop,
        tool_uses=tuple(ToolUse(name=name, input=tool_input) for _ in range(uses)),
        input_tokens=2000, output_tokens=250, request_id="fake-request",
    )


def text_response(stop: str = "end_turn") -> ModelResponse:
    return ModelResponse(stop_reason=stop, text_blocks=1, input_tokens=2000, output_tokens=40,
                         request_id="fake-request")


class ScriptedModelClient:
    """Each converse() call takes the next scripted item; a single callable answers every call."""

    def __init__(self, *items: ModelResponse | Exception | Responder) -> None:
        self.items = list(items)
        self.requests: list[ModelRequest] = []

    def converse(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        item = self.items[0] if len(self.items) == 1 and callable(self.items[0]) else self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item) and not isinstance(item, ModelResponse):
            return item(request)
        return item


def _block(text: str, tag: str) -> Any:
    match = re.search(_BLOCK.format(tag=tag), text, re.DOTALL)
    return json.loads(match.group(1)) if match else None


def copied_claims(request: ModelRequest) -> list[dict[str, Any]]:
    """The claims an ideal model would make from the prompt's facts."""
    paypal = _block(request.user_text, "paypal_data") or {}
    record = _block(request.user_text, "merchant_record") or {}
    txn = paypal.get("transaction") or {}
    pairs = [
        ("transaction_id", "paypal", txn.get("seller_transaction_id")),
        ("amount", "paypal", txn.get("gross_amount")),
        ("transaction_date", "paypal", txn.get("transaction_date_utc")),
        ("seller_protection", "paypal", txn.get("seller_protection_eligible")),
        ("tracking_number", "merchant_record", record.get("tracking_number")),
        ("carrier", "merchant_record", record.get("carrier")),
    ]
    return [{"type": t, "source": s, "value": v} for t, s, v in pairs if v is not None]


def copying_responder(mutate: Mutator | None = None) -> Responder:
    def respond(request: ModelRequest) -> ModelResponse:
        claims = copied_claims(request)
        return tool_response({"claims": mutate(claims) if mutate else claims})
    return respond
