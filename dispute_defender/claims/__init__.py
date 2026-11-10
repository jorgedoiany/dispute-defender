"""Claim schema and deterministic verifier (T-004)."""
from .models import (
    SOURCE_MERCHANT_RECORD,
    SOURCE_PAYPAL,
    Claim,
    ClaimResult,
    MerchantOrderRecord,
    Verdict,
)
from .verifier import SUPPORTED_CLAIM_TYPES, verify_claim, verify_claims

__all__ = [
    "SOURCE_MERCHANT_RECORD",
    "SOURCE_PAYPAL",
    "SUPPORTED_CLAIM_TYPES",
    "Claim",
    "ClaimResult",
    "MerchantOrderRecord",
    "Verdict",
    "verify_claim",
    "verify_claims",
]
