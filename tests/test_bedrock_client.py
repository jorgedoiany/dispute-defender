"""Offline tests for the Bedrock client and model config (T-005).

Bedrock is never called: botocore's Stubber answers every request, and conftest
blocks botocore's HTTP send and the real AWS profile.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import boto3
import pytest
from botocore.exceptions import NoCredentialsError, ReadTimeoutError
from botocore.stub import Stubber

from dispute_defender.drafter import (
    TOOL_NAME,
    BedrockModelClient,
    ModelCallError,
    ModelConfigError,
    ModelNetworkError,
    ModelRequest,
    ModelThrottledError,
    load_model_config,
    tool_spec,
)
from dispute_defender.drafter.bedrock import converse_kwargs, parse_converse_response

FIXTURES = Path(__file__).parent / "fixtures" / "bedrock"
MODEL = "us.anthropic.claude-sonnet-4-6"
SECRET_PROMPT = "PROMPT-MARKER-must-not-leak"
AWS_MESSAGE = "AWS-MESSAGE-MARKER-must-not-leak"


def converse_fixture() -> dict[str, Any]:
    return json.loads((FIXTURES / "converse_submit_claims.json").read_text())


def request() -> ModelRequest:
    return ModelRequest(
        model_id=MODEL, tool_name=TOOL_NAME, system=f"system {SECRET_PROMPT}",
        user_text=f"user {SECRET_PROMPT}", tool=tool_spec(),
    )


class Sleeps(list):
    def __call__(self, seconds: float) -> None:
        self.append(seconds)


@pytest.fixture
def stubbed() -> Any:
    # Fake static keys so boto3 does not search for credentials; Stubber answers before signing.
    client = boto3.client(
        "bedrock-runtime", region_name="us-east-1",
        aws_access_key_id="testing", aws_secret_access_key="testing",
    )
    with Stubber(client) as stubber:
        yield client, stubber
        stubber.assert_no_pending_responses()


def throttle(stubber: Stubber, request_id: str = "req-throttle") -> None:
    stubber.add_client_error(
        "converse", service_error_code="ThrottlingException", service_message=AWS_MESSAGE,
        http_status_code=429, response_meta={"RequestId": request_id},
    )


# Request and response


def test_request_shape_and_parsed_response(stubbed: Any) -> None:
    client, stubber = stubbed
    stubber.add_response("converse", converse_fixture(), expected_params=converse_kwargs(request()))
    response = BedrockModelClient("us-east-1", client=client).converse(request())
    assert response.stop_reason == "tool_use"
    assert len(response.tool_uses) == 1 and response.tool_uses[0].name == TOOL_NAME
    assert response.tool_uses[0].input["claims"][0]["type"] == "transaction_id"
    assert (response.input_tokens, response.output_tokens) == (1200, 180)


def test_converse_kwargs_force_the_tool_without_thinking_or_temperature() -> None:
    kwargs = converse_kwargs(request())
    assert kwargs["modelId"] == MODEL
    assert kwargs["toolConfig"]["toolChoice"] == {"tool": {"name": TOOL_NAME}}
    assert kwargs["toolConfig"]["tools"] == [tool_spec()]
    assert kwargs["inferenceConfig"] == {"maxTokens": 2048}
    assert "additionalModelRequestFields" not in kwargs  # no extended thinking
    assert "temperature" not in json.dumps(kwargs["inferenceConfig"])


def test_request_repr_hides_prompt() -> None:
    assert SECRET_PROMPT not in repr(request())


@pytest.mark.parametrize("raw", [None, [], {}, {"output": "x"}, {"output": {"message": {"content": "x"}}}])
def test_odd_response_shapes_parse_to_nothing(raw: Any) -> None:
    response = parse_converse_response(raw)
    assert response.tool_uses == () and response.stop_reason is None


# Retry on throttling only


def test_throttling_then_success_retries_once(stubbed: Any) -> None:
    client, stubber = stubbed
    throttle(stubber)
    stubber.add_response("converse", converse_fixture())
    sleeps = Sleeps()
    response = BedrockModelClient("us-east-1", client=client, sleep=sleeps).converse(request())
    assert response.stop_reason == "tool_use"
    assert sleeps == [1.0]


def test_throttling_three_times_raises_after_three_attempts(stubbed: Any) -> None:
    client, stubber = stubbed
    for _ in range(3):
        throttle(stubber, "req-last")
    sleeps = Sleeps()
    with pytest.raises(ModelThrottledError) as caught:
        BedrockModelClient("us-east-1", client=client, sleep=sleeps).converse(request())
    assert caught.value.attempts == 3
    assert sleeps == [1.0, 2.0]
    assert str(caught.value) == "Bedrock Converse throttled after 3 attempts request_id=req-last"


@pytest.mark.parametrize(
    ("code", "status"),
    [("AccessDeniedException", 403), ("ValidationException", 400), ("ModelTimeoutException", 408),
     ("ServiceUnavailableException", 503)],
)
def test_other_errors_are_not_retried(stubbed: Any, code: str, status: int) -> None:
    client, stubber = stubbed
    stubber.add_client_error(
        "converse", service_error_code=code, service_message=f"{AWS_MESSAGE} {SECRET_PROMPT}",
        http_status_code=status, response_meta={"RequestId": "req-1"},
    )
    sleeps = Sleeps()
    with pytest.raises(ModelCallError) as caught:
        BedrockModelClient("us-east-1", client=client, sleep=sleeps).converse(request())
    assert sleeps == []
    assert str(caught.value) == f"Bedrock Converse failed: code={code} http={status} request_id=req-1"
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


class RaisingClient:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls = 0

    def converse(self, **_kwargs: Any) -> Any:
        self.calls += 1
        raise self.exc


def test_timeout_is_a_network_error_and_not_retried() -> None:
    fake = RaisingClient(ReadTimeoutError(endpoint_url="https://bedrock-runtime.us-east-1.amazonaws.com"))
    with pytest.raises(ModelNetworkError, match="ReadTimeoutError"):
        BedrockModelClient("us-east-1", client=fake, sleep=Sleeps()).converse(request())
    assert fake.calls == 1


def test_missing_credentials_is_a_config_error() -> None:
    with pytest.raises(ModelConfigError, match="NoCredentialsError"):
        BedrockModelClient("us-east-1", client=RaisingClient(NoCredentialsError())).converse(request())


def test_real_client_without_credentials_fails_safely() -> None:
    """No fake keys and no profile (conftest): boto3 finds no credentials and nothing is sent."""
    with pytest.raises((ModelConfigError, ModelNetworkError, ModelCallError)) as caught:
        BedrockModelClient("us-east-1").converse(request())
    assert SECRET_PROMPT not in str(caught.value)


def test_unknown_error_code_text_is_not_echoed(stubbed: Any) -> None:
    client, stubber = stubbed
    stubber.add_client_error("converse", service_error_code="Weird code; with spaces", http_status_code=400)
    with pytest.raises(ModelCallError) as caught:
        BedrockModelClient("us-east-1", client=client).converse(request())
    assert "code=unknown" in str(caught.value)


# Config


def test_config_reads_env() -> None:
    config = load_model_config({
        "AWS_REGION": "us-east-1", "BEDROCK_MODEL_ID": MODEL,
        "BEDROCK_MODEL_ID_SECONDARY": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    })
    assert config.model("primary") == MODEL
    assert config.model("secondary") == "us.anthropic.claude-haiku-4-5-20251001-v1:0"


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"AWS_REGION": "us-east-1"},
        {"AWS_REGION": " ", "BEDROCK_MODEL_ID": MODEL},
        {"AWS_REGION": "US East", "BEDROCK_MODEL_ID": MODEL},
        {"AWS_REGION": "us-east-1", "BEDROCK_MODEL_ID": "model id with spaces"},
        {"AWS_REGION": "us-east-1", "BEDROCK_MODEL_ID": MODEL, "BEDROCK_MODEL_ID_SECONDARY": "bad id!"},
    ],
)
def test_bad_config_is_rejected(env: dict[str, str]) -> None:
    with pytest.raises(ModelConfigError):
        load_model_config(env)


def test_secondary_is_optional_until_asked_for() -> None:
    config = load_model_config({"AWS_REGION": "us-east-1", "BEDROCK_MODEL_ID": MODEL})
    assert config.secondary_model_id is None
    with pytest.raises(ModelConfigError, match="BEDROCK_MODEL_ID_SECONDARY"):
        config.model("secondary")


def test_config_reads_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", MODEL)
    assert load_model_config().model_id == MODEL
