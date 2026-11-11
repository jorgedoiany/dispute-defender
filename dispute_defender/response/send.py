"""Send gate: decide whether a response may be sent, and build its payload (T-006, ADR-010).

A pure function of a freshly read dispute, the verifier's results and the hash of the
text the merchant was shown. No model, network or clock. Checks, in this order; the
first one that fails gives the refusal:
  1. the dispute does not offer the `provide_evidence` link (the only gate signal;
     `allowed_response_options` is shown for information, never checked)
  2. the tracking number or carrier is not VERIFIED exactly once (PROOF_OF_FULFILLMENT
     needs both)
  3. the carrier is not in ALLOWED_CARRIERS
  4. the renderer returns None (no VERIFIED claim, or a duplicate VERIFIED type)
  5. the notes are longer than MAX_NOTES_CHARS
  6. sha256(notes) differs from the hash of the text the merchant was shown

The tracking info is built from VERIFIED claim values only, never from form input, so
FLAGGED and BLOCKED values cannot reach the payload. The carrier is the same canonical
value the renderer writes in the text.
"""
from __future__ import annotations

import hashlib
import hmac
from collections.abc import Sequence
from dataclasses import dataclass

from dispute_defender.claims import ClaimResult, Verdict
from dispute_defender.paypal import Dispute, Evidence, TrackingInfo

from .carriers import ALLOWED_CARRIERS, canonical_carrier
from .render import render_notes

# Assumed limit for `notes`, not verified against PayPal. Refuse rather than cut the text.
MAX_NOTES_CHARS = 2000

PROVIDE_EVIDENCE_LINK = "provide_evidence"


@dataclass(frozen=True)
class SendPlan:
    evidence: Evidence
    notes: str
    notes_hash: str


@dataclass(frozen=True)
class Refusal:
    reason: str


def notes_hash(notes: str) -> str:
    """SHA-256 hex digest of the notes, carried by the page to confirm what was shown."""
    return hashlib.sha256(notes.encode("utf-8")).hexdigest()


def check_dispute_sendable(dispute: Dispute) -> Refusal | None:
    """Rule 1 alone, so the app can refuse before spending a model call."""
    if not dispute.has_link(PROVIDE_EVIDENCE_LINK):
        return Refusal(
            "PayPal does not offer provide-evidence for this dispute in its current state "
            f"(status {dispute.status}, stage {dispute.stage})"
        )
    return None


def _single_verified(results: Sequence[ClaimResult], type_: str) -> object | None:
    values = [r.claim.value for r in results if r.verdict is Verdict.VERIFIED and r.claim.type == type_]
    return values[0] if len(values) == 1 else None


def prepare_send(dispute: Dispute, results: Sequence[ClaimResult], shown_hash: str) -> SendPlan | Refusal:
    refusal = check_dispute_sendable(dispute)
    if refusal is not None:
        return refusal

    tracking = _single_verified(results, "tracking_number")
    carrier = _single_verified(results, "carrier")
    if not isinstance(tracking, str) or carrier is None:
        return Refusal("proof of fulfillment needs both the tracking number and the carrier VERIFIED")
    carrier_name = canonical_carrier(carrier)
    if carrier_name is None:
        return Refusal(f"carrier is not supported; allowed: {', '.join(ALLOWED_CARRIERS)}")

    notes = render_notes(results)
    if notes is None:
        return Refusal("nothing to send: no VERIFIED claim, or two VERIFIED claims of the same type")

    if len(notes) > MAX_NOTES_CHARS:
        return Refusal(f"response text is longer than {MAX_NOTES_CHARS} characters")

    digest = notes_hash(notes)
    if not isinstance(shown_hash, str) or not hmac.compare_digest(
        digest.encode("ascii"), shown_hash.encode("utf-8")
    ):
        return Refusal("the response text differs from the one shown; review the new draft before approving")

    evidence = Evidence(
        tracking_info=[TrackingInfo(carrier_name=carrier_name, tracking_number=tracking)],
        notes=notes,
    )
    return SendPlan(evidence=evidence, notes=notes, notes_hash=digest)
