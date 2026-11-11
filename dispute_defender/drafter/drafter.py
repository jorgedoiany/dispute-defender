"""draft_claims: one model call, strict output validation, claims for the verifier (T-005, ADR-009).

The model output is rejected as a whole (DraftRejected) unless the model stopped to
call `submit_claims` exactly once with input that passes DraftOutput. Nothing from a
rejected output is returned. Accepted claims still go through the verifier.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from dispute_defender.claims import Claim, MerchantOrderRecord
from dispute_defender.paypal.models import Dispute

from .client import DEFAULT_MAX_TOKENS, ModelClient, ModelRequest, ModelResponse
from .errors import DraftRejected
from .prompt import build_prompt
from .schema import _CLAIM_MODELS, TOOL_NAME, AmountValue, DraftOutput, to_claims, tool_spec

_STOP_REASON = re.compile(r"^[a-z_]{1,32}$")
# Names that may appear in a rejection message. Any other location part (for example
# an extra key the model invented) is replaced, so model text cannot reach the message.
_KNOWN_NAMES = (
    set(DraftOutput.model_fields)
    | set(AmountValue.model_fields)
    | {name for model in _CLAIM_MODELS for name in model.model_fields}
    | {model.model_fields["type"].annotation.__args__[0] for model in _CLAIM_MODELS}
)


@dataclass(frozen=True)
class Draft:
    claims: tuple[Claim, ...]
    model_id: str
    stop_reason: str
    input_tokens: int | None
    output_tokens: int | None
    request_id: str | None


def _loc(parts: tuple[Any, ...]) -> str:
    shown = [str(p) if isinstance(p, int) or p in _KNOWN_NAMES else "<other>" for p in parts]
    return ".".join(shown) or "<input>"


def validate_response(response: ModelResponse) -> DraftOutput:
    """Accept only a single submit_claims call whose input passes DraftOutput."""
    stop = response.stop_reason
    if stop != "tool_use":
        shown = stop if isinstance(stop, str) and _STOP_REASON.fullmatch(stop) else "unknown"
        raise DraftRejected(f"model did not call {TOOL_NAME} (stop reason: {shown})")
    if len(response.tool_uses) != 1:
        raise DraftRejected(f"expected exactly one tool call, got {len(response.tool_uses)}")
    (use,) = response.tool_uses
    if use.name != TOOL_NAME:
        raise DraftRejected(f"model called a tool other than {TOOL_NAME}")
    if not isinstance(use.input, dict):
        raise DraftRejected(f"{TOOL_NAME} input is not a JSON object")
    try:
        return DraftOutput.model_validate(use.input)
    except ValidationError as exc:
        problems = "; ".join(
            f"{_loc(err['loc'])}: {err['type']}"
            for err in exc.errors(include_input=False, include_url=False, include_context=False)
        )
        raise DraftRejected(f"{TOOL_NAME} input failed validation ({problems})"[:500]) from None


def draft_claims(
    dispute: Dispute,
    record: MerchantOrderRecord | None = None,
    *,
    client: ModelClient,
    model_id: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> Draft:
    """Ask the model for claims about `dispute`. Raises DrafterError subclasses on failure."""
    prompt = build_prompt(dispute, record)
    request = ModelRequest(
        model_id=model_id, tool_name=TOOL_NAME, system=prompt.system,
        user_text=prompt.user_text, tool=tool_spec(), max_tokens=max_tokens,
    )
    response = client.converse(request)
    output = validate_response(response)
    return Draft(
        claims=tuple(to_claims(output)),
        model_id=model_id,
        stop_reason="tool_use",
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        request_id=response.request_id,
    )
