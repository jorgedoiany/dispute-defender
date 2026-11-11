# Evaluation (T-007): SIMULATED DATA

**Everything in this folder is simulated.** The scenarios are not real disputes and
hold no real or personal data. The numbers in `results.md` describe these simulated
scenarios only; they do **not** describe real-world accuracy.

Why simulated: each PayPal sandbox dispute needs manual buyer steps in the browser
(T-002, ADR-007), so 24 disputes with known ground truth cannot be made in the sandbox.

## Contents
- `scenarios/*.json`: 24 simulated scenarios, written for this evaluation (not
  recorded from PayPal). Each has `"simulated": true`; the loader refuses any file
  without it. IDs start with `SIM`, buyer fields use `FAKE-...` values and
  `example.invalid`, and buyer messages start with "SIMULATED".
- `frozen.json`: hashes of the scenarios, scoring rules, prompt and pipeline, recorded
  before the live run (`scripts/run_evaluation.py freeze`).
- `DECLARED_CHANGES.md`: any change made after seeing results. Shown in the report.
- `results/`: raw per-call results (`raw-*.jsonl`, no prompts or credentials) and
  the Part B fault-injection results (`faults.json`).
- `results.md`: the generated report.

## Scenario format
- `dispute`: a PayPal-shaped dispute body, parsed with the app's `Dispute` model.
  Every scenario offers the `provide_evidence` link so the send gate can be run.
- `merchant_record`: the merchant's order record, or `null`.
- `ground_truth`: one entry for each of the six claim types (ADR-011):
  - `{"expect": [...]}`: accepted values, compared as exact JSON. Equivalent forms are
    listed by hand: an amount's exact string plus Decimal-equal forms with up to two
    decimals; a carrier's record value plus its upper, lower and title case.
  - `{"absent": true}`: the fact is missing; the claim must not be made.
  - `{"unsupported": true}`: the model may make the claim (the prompt gives it the
    value), but it must not be VERIFIED or sent.
- `expected_send`: `send` or `refuse`, what the send gate should do with the correct claims.
- Optional `local_date` (date scenarios) and `injected_values` (prompt-injection
  scenarios), used by Part B.

## Categories
normal (N1-N3), transactions (M1-M4), seller_protection (S1), amount_currency (A1-A3),
date_timezone (D1-D2), merchant_record (R1-R3), carrier (C1-C3), prompt_injection
(I1-I3), hostile_characters (H1-H2).

Scoring definitions: ADR-011 in `DECISIONS.md`.
