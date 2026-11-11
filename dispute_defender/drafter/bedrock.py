"""Bedrock implementation of ModelClient, using the Converse API (T-005, ADR-003, ADR-009).

- Forced tool: `toolChoice = {"tool": {"name": ...}}`. Whether each model accepts a
  forced tool choice is not verified here; it is checked in the first live run.
- No extended thinking and no temperature are sent.
- Timeouts: 5 s connect, 60 s read. botocore's own retries are off.
- Retry: only ThrottlingException, at most 3 attempts in total, 1 s then 2 s apart.
- Credentials: boto3's standard chain (AWS CLI profile). Nothing is read from the repo.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
    PartialCredentialsError,
    ProfileNotFound,
    ReadTimeoutError,
)

from .client import ModelRequest, ModelResponse, ToolUse
from .config import ModelConfig
from .errors import ModelCallError, ModelConfigError, ModelNetworkError, ModelThrottledError

THROTTLING = "ThrottlingException"
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (1.0, 2.0)
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 60


def converse_kwargs(request: ModelRequest) -> dict[str, Any]:
    """The exact keyword arguments sent to `bedrock-runtime` `converse`."""
    return {
        "modelId": request.model_id,
        "system": [{"text": request.system}],
        "messages": [{"role": "user", "content": [{"text": request.user_text}]}],
        "inferenceConfig": {"maxTokens": request.max_tokens},
        "toolConfig": {
            "tools": [request.tool],
            "toolChoice": {"tool": {"name": request.tool_name}},
        },
    }


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_converse_response(raw: Any) -> ModelResponse:
    """Pick the parts the drafter needs. Shape problems give an empty result, never an exception."""
    raw = raw if isinstance(raw, dict) else {}
    output = raw.get("output") if isinstance(raw.get("output"), dict) else {}
    message = output.get("message") if isinstance(output.get("message"), dict) else {}
    content = message.get("content") if isinstance(message.get("content"), list) else []
    tool_uses: list[ToolUse] = []
    text_blocks = 0
    for block in content:
        if not isinstance(block, dict):
            continue
        if isinstance(block.get("toolUse"), dict):
            use = block["toolUse"]
            name = use.get("name")
            tool_uses.append(ToolUse(name=name if isinstance(name, str) else "", input=use.get("input")))
        elif "text" in block:
            text_blocks += 1
    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
    metadata = raw.get("ResponseMetadata") if isinstance(raw.get("ResponseMetadata"), dict) else {}
    stop_reason = raw.get("stopReason")
    return ModelResponse(
        stop_reason=stop_reason if isinstance(stop_reason, str) else None,
        tool_uses=tuple(tool_uses),
        text_blocks=text_blocks,
        input_tokens=_int_or_none(usage.get("inputTokens")),
        output_tokens=_int_or_none(usage.get("outputTokens")),
        request_id=metadata.get("RequestId") if isinstance(metadata.get("RequestId"), str) else None,
    )


def _client_error_fields(exc: ClientError) -> tuple[Any, Any, Any]:
    response = exc.response if isinstance(exc.response, dict) else {}
    error = response.get("Error") if isinstance(response.get("Error"), dict) else {}
    metadata = response.get("ResponseMetadata") if isinstance(response.get("ResponseMetadata"), dict) else {}
    return error.get("Code"), metadata.get("HTTPStatusCode"), metadata.get("RequestId")


class BedrockModelClient:
    def __init__(
        self,
        region: str,
        *,
        client: Any = None,
        max_attempts: int = MAX_ATTEMPTS,
        backoff: Sequence[float] = BACKOFF_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1 or len(backoff) < max_attempts - 1:
            raise ValueError("backoff needs one delay per retry")
        self._client = client or boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=Config(
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                read_timeout=READ_TIMEOUT_SECONDS,
                retries={"total_max_attempts": 1, "mode": "standard"},
            ),
        )
        self._max_attempts = max_attempts
        self._backoff = tuple(backoff)
        self._sleep = sleep

    @classmethod
    def from_config(cls, config: ModelConfig, **kwargs: Any) -> BedrockModelClient:
        return cls(config.region, **kwargs)

    def converse(self, request: ModelRequest) -> ModelResponse:
        kwargs = converse_kwargs(request)
        for attempt in range(1, self._max_attempts + 1):
            try:
                raw = self._client.converse(**kwargs)
            except ClientError as exc:
                code, status, request_id = _client_error_fields(exc)
                if code != THROTTLING:
                    raise ModelCallError(code=code, http_status=status, request_id=request_id) from None
                if attempt == self._max_attempts:
                    raise ModelThrottledError(attempts=attempt, request_id=request_id) from None
                self._sleep(self._backoff[attempt - 1])
                continue
            except (NoCredentialsError, PartialCredentialsError, ProfileNotFound) as exc:
                raise ModelConfigError(f"AWS credentials not usable: {type(exc).__name__}") from None
            except (ReadTimeoutError, ConnectTimeoutError, EndpointConnectionError, ConnectionClosedError) as exc:
                raise ModelNetworkError(f"Bedrock Converse network error: {type(exc).__name__}") from None
            except BotoCoreError as exc:
                raise ModelCallError(code=type(exc).__name__) from None
            return parse_converse_response(raw)
        raise AssertionError("unreachable")  # pragma: no cover
