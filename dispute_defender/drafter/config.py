"""Model configuration from environment variables (ADR-003). Model IDs are config, not code."""
from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from .errors import ModelConfigError

ENV_REGION = "AWS_REGION"
ENV_MODEL_ID = "BEDROCK_MODEL_ID"
ENV_MODEL_ID_SECONDARY = "BEDROCK_MODEL_ID_SECONDARY"

_REGION = re.compile(r"^[a-z]{2}(-[a-z]+)+-[0-9]$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")

Which = Literal["primary", "secondary"]


@dataclass(frozen=True)
class ModelConfig:
    region: str
    model_id: str
    secondary_model_id: str | None = None

    def model(self, which: Which = "primary") -> str:
        if which == "primary":
            return self.model_id
        if which == "secondary" and self.secondary_model_id:
            return self.secondary_model_id
        raise ModelConfigError(f"missing environment variable: {ENV_MODEL_ID_SECONDARY}")


def load_model_config(env: Mapping[str, str] | None = None) -> ModelConfig:
    """Read region and model IDs from the environment (os.environ by default).

    AWS credentials are not read here: boto3 finds them through its standard
    credential chain (the AWS CLI profile). This does not read `.env`.
    """
    source = os.environ if env is None else env
    region = source.get(ENV_REGION, "").strip()
    model_id = source.get(ENV_MODEL_ID, "").strip()
    secondary = source.get(ENV_MODEL_ID_SECONDARY, "").strip() or None
    missing = [name for name, value in ((ENV_REGION, region), (ENV_MODEL_ID, model_id)) if not value]
    if missing:
        raise ModelConfigError(f"missing environment variables: {', '.join(missing)}")
    if not _REGION.fullmatch(region):
        raise ModelConfigError(f"{ENV_REGION} is not a valid AWS region name")
    for name, value in ((ENV_MODEL_ID, model_id), (ENV_MODEL_ID_SECONDARY, secondary)):
        if value is not None and not _MODEL_ID.fullmatch(value):
            raise ModelConfigError(f"{name} is not a valid model ID")
    return ModelConfig(region=region, model_id=model_id, secondary_model_id=secondary)
