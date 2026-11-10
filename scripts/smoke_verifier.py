#!/usr/bin/env python3
"""Live read-only check of the claim verifier against the PayPal sandbox (T-004).

One dispute per run. Loads `.env`, fetches the dispute with the validated client
(PayPalClient.from_env() refuses any host other than api-m.sandbox.paypal.com; only GET
calls are made) and runs verify_claims() on a fixed list of test claims with a fixed
merchant record. Prints one line per claim: verdict, expected verdict and reason.
Never prints credentials, tokens, raw bodies or buyer data (buyer fields are dropped by
the model before the verifier sees them).

The claims are sandbox test values chosen by the author. The merchant record is a test
record, not a real order. Only the two disputes below are accepted, because each claim
list is tied to that dispute's transaction.

Usage:
  scripts/smoke_verifier.py --dispute-id PP-R-KXL-10197854
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dispute_defender.claims import Claim, MerchantOrderRecord, Verdict, verify_claims  # noqa: E402
from dispute_defender.paypal import PayPalClient, PayPalError  # noqa: E402

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
V, B = Verdict.VERIFIED, Verdict.BLOCKED


@dataclass(frozen=True)
class Case:
    transaction_id: str
    utc_date: str  # the transaction date PayPal is expected to show, in UTC
    other_date: str  # a neighbouring date that must be BLOCKED under the UTC rule


CASES = {
    "PP-R-KXL-10197854": Case("9J725035KE512071R", utc_date="2026-11-10", other_date="2026-11-09"),
    "PP-R-HBV-10197617": Case("54X87564PT289050U", utc_date="2026-11-09", other_date="2026-11-10"),
}


def claims_for(case: Case) -> list[tuple[Claim, Verdict | None]]:
    """Test claims with the expected verdict; None means no expectation was stated."""
    usd = lambda value: {"value": value, "currency_code": "USD"}  # noqa: E731
    return [
        (Claim(type="transaction_id", value=case.transaction_id, source="paypal"), V),
        (Claim(type="amount", value=usd("10.00"), source="paypal"), V),
        (Claim(type="transaction_date", value=case.utc_date, source="paypal"), V),
        (Claim(type="transaction_date", value=case.other_date, source="paypal"), B),
        (Claim(type="amount", value=usd("12.00"), source="paypal"), B),
        (Claim(type="tracking_number", value="122533485", source="merchant_record"), V),
        (Claim(type="carrier", value="fedex", source="merchant_record"), V),
        (Claim(type="tracking_number", value="000", source="merchant_record"), B),
        (Claim(type="seller_protection", value=True, source="paypal"), None),
    ]


def describe(claim: Claim) -> str:
    value = claim.value
    if isinstance(value, dict):
        value = f"{value.get('value')} {value.get('currency_code')}"
    return f"{claim.type}={value}"


def run(dispute_id: str) -> int:
    case = CASES[dispute_id]
    record = MerchantOrderRecord(transaction_id=case.transaction_id, tracking_number="122533485", carrier="FedEx")
    dispute = PayPalClient.from_env().get_dispute(dispute_id)
    print(f"[dispute] OK | id={dispute.dispute_id} status={dispute.status} stage={dispute.stage} "
          f"transactions={len(dispute.transactions)}")
    print("[record] test merchant record: transaction_id, tracking_number, carrier given")

    pairs = claims_for(case)
    results = verify_claims(dispute, [claim for claim, _ in pairs], record)
    unmet = 0
    for i, (result, (_, expected)) in enumerate(zip(results, pairs), start=1):
        if expected is None:
            mark = "expected: not stated"
        elif result.verdict is expected:
            mark = f"expected {expected}: met"
        else:
            mark = f"expected {expected}: NOT MET"
            unmet += 1
        print(f"[{i}] {result.verdict:<8} | {describe(result.claim)} | {mark} | {result.reason}")
    stated = sum(expected is not None for _, expected in pairs)
    print(f"[summary] {len(results)} claims; expectations met {stated - unmet}/{stated}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="T-004 read-only verifier check. Sandbox only.")
    parser.add_argument("--dispute-id", required=True, choices=sorted(CASES))
    args = parser.parse_args()
    load_dotenv(ENV_PATH, override=True)
    try:
        return run(args.dispute_id)
    except PayPalError as exc:
        print(f"[verifier] FAILED | {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
