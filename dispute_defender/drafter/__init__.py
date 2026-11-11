"""Model drafter (T-005, ADR-009): builds the prompt and defines the claims the model must return.

The model only drafts claims. Every claim is checked by the deterministic verifier
before the merchant sees it, and no model free text is ever sent to PayPal.
"""
from .bedrock import BedrockModelClient
from .client import ModelClient, ModelRequest, ModelResponse, ToolUse
from .config import ModelConfig, load_model_config
from .errors import (
    DrafterError,
    DraftRejected,
    ModelCallError,
    ModelConfigError,
    ModelNetworkError,
    ModelThrottledError,
)
from .prompt import Prompt, build_prompt, buyer_messages, facts
from .schema import (
    DRAFT_CLAIM_SOURCES,
    MAX_CLAIMS,
    TOOL_NAME,
    DraftOutput,
    to_claims,
    tool_input_schema,
    tool_spec,
)

__all__ = [
    "DRAFT_CLAIM_SOURCES",
    "MAX_CLAIMS",
    "TOOL_NAME",
    "BedrockModelClient",
    "DraftOutput",
    "DraftRejected",
    "DrafterError",
    "ModelCallError",
    "ModelClient",
    "ModelConfig",
    "ModelConfigError",
    "ModelNetworkError",
    "ModelRequest",
    "ModelResponse",
    "ModelThrottledError",
    "Prompt",
    "ToolUse",
    "build_prompt",
    "buyer_messages",
    "facts",
    "load_model_config",
    "to_claims",
    "tool_input_schema",
    "tool_spec",
]
