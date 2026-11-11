# T-007 evaluation results: SIMULATED DATA

> **Simulated scenarios only.** These numbers describe 24 simulated disputes written for this evaluation, with hand-written ground truth. They do **not** describe real-world accuracy, real PayPal disputes or real buyers.

Generated 2026-11-11T03:57:46+00:00 by `scripts/run_evaluation.py report`. Scoring definitions: ADR-011 in `DECISIONS.md`. Scenarios: `evaluation/scenarios/` (simulated).

## Freeze

Scenarios, scoring rules, prompt and pipeline hashes were recorded at 2026-11-11T03:57:46+00:00 (`evaluation/frozen.json`, 1 freeze(s)).
No live call recorded yet. The current hashes match the first freeze.

| hash | first freeze | current |
|---|---|---|
| pipeline | `9fda44771fd4b7af` | `9fda44771fd4b7af` |
| prompt | `19c3225b501487b9` | `19c3225b501487b9` |
| scenarios | `4b78bee865d85b1a` | `4b78bee865d85b1a` |
| scoring | `1ed210f06a7a4b59` | `1ed210f06a7a4b59` |

## Declared changes

None declared.

## Part A: model drafts on simulated scenarios (live Bedrock)

Not run yet. Run `scripts/run_evaluation.py run --confirm-spend` (see AGENTS.md), then `scripts/run_evaluation.py report`.

## Part B: fault injection into simulated claims (offline)

1192 fault cases on 24 simulated scenarios. Each case alters one claim of a scenario's correct claims and runs the real verifier and send gate (claim layer), or returns a faulty tool call to `draft_claims` (tool-input layer). Deterministic and free.

Baseline: 0 of 128 correct claims wrongly rejected.

### Faults the verifier should catch

| fault group | applied | caught | missed | expected misses | faulted value reached a send plan |
|---|---|---|---|---|---|
| amount | 190 | 190 | 0 | 0 | 0 |
| date | 105 | 105 | 0 | 0 | 0 |
| merchant_record | 43 | 0 | 0 | 43 | 20 |
| seller_protection | 43 | 43 | 0 | 0 | 0 |
| source_type | 304 | 304 | 0 | 0 | 0 |
| tool_input | 288 | 288 | 0 | 0 | 0 |
| tracking_carrier | 68 | 68 | 0 | 0 | 0 |
| transaction_id | 67 | 67 | 0 | 0 | 0 |

Expected misses are outside the verifier's reach by design: the merchant record itself is wrong and the claim copies it, so the claim matches the record. When the scenario sends, that wrong value reaches the send plan.

### Correct values that must not be rejected

| group | applied | VERIFIED | rejected |
|---|---|---|---|
| benign_variant | 82 | 82 | 0 |
| local_date | 2 | 0 | 2 |

`benign_variant`: equivalent values (an extra trailing zero, carrier case or spaces). `local_date`: the correct local date near midnight, BLOCKED by design because dates are compared in UTC (ADR-008); a known false rejection.

The faults were written with knowledge of the verifier's rules, so a high catch rate is expected by construction.

## Limitations

- All scenarios are simulated and were written by the author with knowledge of the verifier's rules. One dispute reason (item not received); no real buyers or merchants.
- Small sample: 24 scenarios with up to 3 repetitions per model. Zero observed errors does not mean a zero error rate; no confidence intervals are claimed.
- The ground truth is hand-written and may itself be wrong; every claim where it and the verifier disagree is listed for review.
- The model only ever sees the UTC transaction date (computed by code). The date scenarios test whether a local date in a buyer message lures the model, not time-zone reasoning.
- The no-verifier counterfactual is computed from the same model outputs, not from a separate experiment. It keeps schema validation, so it is conservative and understates the verifier's value.
- The verifier trusts the merchant record: a wrong record is not caught (Part B expected misses).
- Part B faults were designed against known verifier rules, so a high catch rate is expected by construction.
- Two models, one region, one run window, no temperature sent (the model default). Other model versions or days may behave differently.
- The prompt-injection texts were written by the author; they are not adversarially optimised.
- Token estimates in the dry run are a heuristic. Any cost shown uses author-supplied prices.
- Nothing here says whether a response would win a dispute, or what PayPal would accept.
