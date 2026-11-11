"""The app's own pipeline after drafting, applied to evaluation claims (T-007).

Verdicts come from `verify_claims`; the send outcome comes from `render_notes` and
`prepare_send`, with the shown hash taken from the rendered text (what the approval
page would show). No rule is re-implemented here.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from dispute_defender.claims import Claim, ClaimResult, MerchantOrderRecord, verify_claims
from dispute_defender.paypal import Dispute
from dispute_defender.response import SendPlan, notes_hash, prepare_send, render_notes


@dataclass(frozen=True)
class SendOutcome:
    sent: bool  # prepare_send returned a SendPlan
    reason: str | None  # the Refusal reason, or None when a plan was returned


@dataclass(frozen=True)
class PipelineResult:
    results: list[ClaimResult]
    send: SendOutcome


def send_outcome(dispute: Dispute, results: Sequence[ClaimResult]) -> SendOutcome:
    notes = render_notes(results)
    plan = prepare_send(dispute, results, notes_hash(notes) if notes else "")
    if isinstance(plan, SendPlan):
        return SendOutcome(sent=True, reason=None)
    return SendOutcome(sent=False, reason=plan.reason)


def run_pipeline(dispute: Dispute, claims: Sequence[Claim], record: MerchantOrderRecord | None) -> PipelineResult:
    results = verify_claims(dispute, list(claims), record)
    return PipelineResult(results=results, send=send_outcome(dispute, results))
