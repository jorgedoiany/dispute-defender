"""Merchant form input -> MerchantOrderRecord (T-006, ADR-010).

The form holds only the merchant's own shipping record: a tracking number and a carrier
from the fixed list. Nothing else from the browser is used, and verdicts never are.
"""
from __future__ import annotations

import re

from dispute_defender.claims import MerchantOrderRecord
from dispute_defender.response import ALLOWED_CARRIERS

_TRACKING = re.compile(r"^[A-Za-z0-9-]{1,64}$")


class FormError(ValueError):
    """Invalid form input. The message is generic and safe to show."""


def merchant_record(tracking: object, carrier: object) -> MerchantOrderRecord:
    tracking_value = tracking.strip() if isinstance(tracking, str) else ""
    if not _TRACKING.fullmatch(tracking_value):
        raise FormError("tracking number must be 1 to 64 letters, digits or hyphens")
    if not isinstance(carrier, str) or carrier not in ALLOWED_CARRIERS:
        raise FormError(f"carrier must be one of: {', '.join(ALLOWED_CARRIERS)}")
    return MerchantOrderRecord(tracking_number=tracking_value, carrier=carrier)
