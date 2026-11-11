"""Fixed carrier list and its canonical PayPal values (T-006, ADR-010).

Used by both the renderer and the send gate, so the response text and the payload's
`carrier_name` always show the same value.
"""
from __future__ import annotations

# PayPal documents `carrier_name` as an enum. Only FEDEX has been sent and accepted in the
# sandbox (T-002, T-003). Before adding another carrier, check its exact enum value in
# PayPal's API reference and in the sandbox.
ALLOWED_CARRIERS: tuple[str, ...] = ("FEDEX",)


def canonical_carrier(value: object) -> str | None:
    """The PayPal enum value for `value` (trimmed, case-insensitive), or None if not allowed."""
    if not isinstance(value, str):
        return None
    wanted = value.strip().casefold()
    return next((c for c in ALLOWED_CARRIERS if c.casefold() == wanted), None)
