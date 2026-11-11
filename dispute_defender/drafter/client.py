"""The model client interface (T-005, ADR-009).

The drafter depends only on `ModelClient`. `BedrockModelClient` is one implementation;
tests use a fake. Prompt text and tool inputs are kept out of repr so they are not
logged by accident.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_MAX_TOKENS = 2048


@dataclass(frozen=True)
class ModelRequest:
    model_id: str
    tool_name: str
    system: str = field(repr=False)
    user_text: str = field(repr=False)
    tool: dict[str, Any] = field(repr=False)
    max_tokens: int = DEFAULT_MAX_TOKENS


@dataclass(frozen=True)
class ToolUse:
    name: str
    input: Any = field(repr=False)


@dataclass(frozen=True)
class ModelResponse:
    stop_reason: str | None
    tool_uses: tuple[ToolUse, ...] = ()
    text_blocks: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    request_id: str | None = None


class ModelClient(Protocol):
    def converse(self, request: ModelRequest) -> ModelResponse:
        """Send one request with one forced tool and return the parsed response.

        Raises a DrafterError subclass on failure; never returns partial data.
        """
        ...
