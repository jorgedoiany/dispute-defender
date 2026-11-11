#!/usr/bin/env python3
"""Live check of the Bedrock drafter (T-005). Read only towards PayPal.

One dispute per run:
  1. GET the dispute from the PayPal sandbox with the validated client
     (PayPalClient.from_env() refuses any host other than api-m.sandbox.paypal.com).
  2. One Bedrock Converse call (billed) with the primary model, or the secondary
     model with --model secondary. Region and model IDs come from AWS_REGION,
     BEDROCK_MODEL_ID and BEDROCK_MODEL_ID_SECONDARY; credentials from the AWS CLI
     profile through boto3's credential chain.
  3. The deterministic verifier checks every drafted claim.
Nothing is sent to PayPal or to the buyer.

Prints only: dispute status, message count, model ID, stop reason, token counts,
request ID, and each claim's type, source, value (cut to 60 characters) and verdict.
Never prints credentials, the prompt, buyer message text or the raw model response.

For the two known sandbox disputes a fixed test merchant record is used (the same
as scripts/smoke_verifier.py); --no-record leaves it out. Other dispute IDs run
without a record.

Usage:
  scripts/smoke_drafter.py --dispute-id PP-R-KXL-10197854 [--model secondary] [--no-record]

Exit codes: 0 drafted and verified, 1 PayPal/AWS/config error, 2 draft rejected.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dispute_defender.claims import Claim, MerchantOrderRecord, Verdict, verify_claims  # noqa: E402
from dispute_defender.drafter import (  # noqa: E402
    BedrockModelClient,
    DrafterError,
    DraftRejected,
    draft_claims,
    load_model_config,
)
from dispute_defender.paypal import PayPalClient, PayPalError, check_dispute_id  # noqa: E402

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
VALUE_LIMIT = 60
_UNPRINTABLE = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁠-⁩﻿]")

# Test merchant records (not real orders), keyed by sandbox dispute ID.
TEST_RECORDS = {
    "PP-R-KXL-10197854": MerchantOrderRecord(
        transaction_id="9J725035KE512071R", tracking_number="122533485", carrier="FedEx"),
    "PP-R-HBV-10197617": MerchantOrderRecord(
        transaction_id="54X87564PT289050U", tracking_number="122533485", carrier="FedEx"),
}


def shown_value(claim: Claim) -> str:
    """Claim values come from the model, which may have copied buyer text: cut and clean them."""
    value: Any = claim.value
    text = json.dumps(value, sort_keys=True, ensure_ascii=False) if isinstance(value, dict) else str(value)
    text = _UNPRINTABLE.sub("", text)
    return text if len(text) <= VALUE_LIMIT else text[:VALUE_LIMIT] + "..."


def run(args: argparse.Namespace) -> int:
    config = load_model_config()
    model_id = config.model(args.model)
    dispute = PayPalClient.from_env().get_dispute(args.dispute_id)
    print(f"[dispute] OK | id={dispute.dispute_id} status={dispute.status} stage={dispute.stage} "
          f"transactions={len(dispute.transactions)} messages={len(dispute.messages)} (text not printed)")

    record = None if args.no_record else TEST_RECORDS.get(dispute.dispute_id)
    print(f"[record] {'test merchant record used' if record else 'no merchant record'}")

    client = BedrockModelClient.from_config(config)
    try:
        draft = draft_claims(dispute, record, client=client, model_id=model_id)
    except DraftRejected as exc:
        print(f"[model] {args.model} | {model_id}")
        print(f"[draft] REJECTED | {exc}")
        return 2
    print(f"[model] {args.model} | {model_id} | stop={draft.stop_reason} | "
          f"tokens in={draft.input_tokens} out={draft.output_tokens} | request_id={draft.request_id}")
    print(f"[draft] schema OK | {len(draft.claims)} claim(s)")

    results = verify_claims(dispute, list(draft.claims), record)
    for i, result in enumerate(results, start=1):
        claim = result.claim
        print(f"[{i}] {result.verdict:<8} | {claim.type} ({claim.source}) = {shown_value(claim)} | {result.reason}")
    counts = Counter(r.verdict for r in results)
    print("[summary] " + " / ".join(f"{v.value} {counts.get(v, 0)}" for v in Verdict))
    return 0


def dispute_id_arg(value: str) -> str:
    try:
        return check_dispute_id(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="T-005 live drafter check: PayPal sandbox GET, one Bedrock call, verifier. Nothing is sent.")
    parser.add_argument("--dispute-id", required=True, type=dispute_id_arg)
    parser.add_argument("--model", choices=("primary", "secondary"), default="primary",
                        help="BEDROCK_MODEL_ID (primary, default) or BEDROCK_MODEL_ID_SECONDARY")
    parser.add_argument("--no-record", action="store_true", help="draft without the test merchant record")
    args = parser.parse_args()
    load_dotenv(ENV_PATH, override=True)
    try:
        return run(args)
    except (PayPalError, DrafterError) as exc:
        print(f"[drafter] FAILED | {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
