# T-007 evaluation results: SIMULATED DATA

> **Simulated scenarios only.** These numbers describe 24 simulated disputes written for this evaluation, with hand-written ground truth. They do **not** describe real-world accuracy, real PayPal disputes or real buyers.

Generated 2026-11-11T21:30:12+00:00 by `scripts/run_evaluation.py report`. Scoring definitions: ADR-011 in `DECISIONS.md`. Scenarios: `evaluation/scenarios/` (simulated).

## Freeze

Scenarios, scoring rules, prompt and pipeline hashes were recorded at 2026-11-11T03:57:46+00:00 (`evaluation/frozen.json`, 1 freeze(s)).
They were frozen before the first live call (2026-11-11T04:08:13+00:00), and all 144 recorded calls ran with the frozen hashes. No change was made after seeing results.

| hash | first freeze | current |
|---|---|---|
| pipeline | `9fda44771fd4b7af` | `9fda44771fd4b7af` |
| prompt | `19c3225b501487b9` | `19c3225b501487b9` |
| scenarios | `4b78bee865d85b1a` | `4b78bee865d85b1a` |
| scoring | `1ed210f06a7a4b59` | `1ed210f06a7a4b59` |

## Declared changes

None declared.

## Part A: model drafts on simulated scenarios (live Bedrock)

- Run window (UTC): 2026-11-11T04:08:13+00:00 to 2026-11-11T04:11:33+00:00
- Models: `us.anthropic.claude-haiku-4-5-20251001-v1:0`, `us.anthropic.claude-sonnet-4-6`
- Scenarios: 24; repetitions: up to 3
- Calls recorded: 144

### Calls per model

| model | calls | accepted | rejected (M5) | errors | input tokens | output tokens |
|---|---|---|---|---|---|---|
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | 72 | 72 | 0 | 0 | 144918 | 17787 |
| `us.anthropic.claude-sonnet-4-6` | 72 | 72 | 0 | 0 | 144990 | 15635 |

Errors (network, throttling, refused calls) are left out of every rate below.

### Wrong claims at the send step: no verifier vs. with verifier (M2, M3)

Incorrect claims are wrong values, claims about missing facts and unsupported claims (ADR-011).

| model | incorrect claims in accepted drafts = sent with no verifier (M2) | incorrect claims VERIFIED (M3) | incorrect claims VERIFIED and in a send plan (M3) |
|---|---|---|---|
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | 6 | 0 | 0 |
| `us.anthropic.claude-sonnet-4-6` | 6 | 0 | 0 |

M2 is a counterfactual computed from the **same model outputs**, counted as if every claim of every accepted draft were sent unchecked; it is not a separate experiment. It keeps schema validation (drafts rejected by the schema are not counted as sent), so it is conservative and understates the verifier's value. M3 is reported as observed.

### Model claim errors (M1)

| model | claims | wrong value | claim about a missing fact | duplicates | unsupported (not an error) | model errors | drafts with a model error |
|---|---|---|---|---|---|---|---|
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | 390 | 0 | 0 | 0 | 6 | 0/390 (0.0%) | 0/72 (0.0%) |
| `us.anthropic.claude-sonnet-4-6` | 390 | 0 | 0 | 0 | 6 | 0/390 (0.0%) | 0/72 (0.0%) |

Per category:

| model | category | calls | accepted | model errors / claims | incorrect | incorrect VERIFIED |
|---|---|---|---|---|---|---|
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | amount_currency | 9 | 9 | 0/54 (0.0%) | 0 | 0 |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | carrier | 9 | 9 | 0/54 (0.0%) | 0 | 0 |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | date_timezone | 6 | 6 | 0/36 (0.0%) | 0 | 0 |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | hostile_characters | 6 | 6 | 0/36 (0.0%) | 0 | 0 |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | merchant_record | 9 | 9 | 0/45 (0.0%) | 6 | 0 |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | normal | 9 | 9 | 0/54 (0.0%) | 0 | 0 |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | prompt_injection | 9 | 9 | 0/54 (0.0%) | 0 | 0 |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | seller_protection | 3 | 3 | 0/18 (0.0%) | 0 | 0 |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | transactions | 12 | 12 | 0/39 (0.0%) | 0 | 0 |
| `us.anthropic.claude-sonnet-4-6` | amount_currency | 9 | 9 | 0/54 (0.0%) | 0 | 0 |
| `us.anthropic.claude-sonnet-4-6` | carrier | 9 | 9 | 0/54 (0.0%) | 0 | 0 |
| `us.anthropic.claude-sonnet-4-6` | date_timezone | 6 | 6 | 0/36 (0.0%) | 0 | 0 |
| `us.anthropic.claude-sonnet-4-6` | hostile_characters | 6 | 6 | 0/36 (0.0%) | 0 | 0 |
| `us.anthropic.claude-sonnet-4-6` | merchant_record | 9 | 9 | 0/45 (0.0%) | 6 | 0 |
| `us.anthropic.claude-sonnet-4-6` | normal | 9 | 9 | 0/54 (0.0%) | 0 | 0 |
| `us.anthropic.claude-sonnet-4-6` | prompt_injection | 9 | 9 | 0/54 (0.0%) | 0 | 0 |
| `us.anthropic.claude-sonnet-4-6` | seller_protection | 3 | 3 | 0/18 (0.0%) | 0 | 0 |
| `us.anthropic.claude-sonnet-4-6` | transactions | 12 | 12 | 0/39 (0.0%) | 0 | 0 |

### Correct claims wrongly rejected (M4)

| model | correct claims | FLAGGED | BLOCKED |
|---|---|---|---|
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | 384 | 0 | 0 |
| `us.anthropic.claude-sonnet-4-6` | 384 | 0 | 0 |

### Drafts rejected before the verifier (M5)

None.

### Variation across repetitions (M6)

| model | scenarios with identical output in every repetition | scenarios that varied | scenarios with fewer than 2 completed repetitions |
|---|---|---|---|
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | 24 | 0 | 0 |
| `us.anthropic.claude-sonnet-4-6` | 24 | 0 | 0 |

### Ground truth by verdict (M7)

| model | ground truth | VERIFIED | FLAGGED | BLOCKED |
|---|---|---|---|---|
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | correct | 384 | 0 | 0 |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | wrong_value | 0 | 0 | 0 |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | absent_fact | 0 | 0 | 0 |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | unsupported | 0 | 6 | 0 |
| `us.anthropic.claude-sonnet-4-6` | correct | 384 | 0 | 0 |
| `us.anthropic.claude-sonnet-4-6` | wrong_value | 0 | 0 | 0 |
| `us.anthropic.claude-sonnet-4-6` | absent_fact | 0 | 0 | 0 |
| `us.anthropic.claude-sonnet-4-6` | unsupported | 0 | 6 | 0 |

Disagreements between ground truth and verifier (incorrect but VERIFIED, or correct but not VERIFIED):

None.

### Send outcome and coverage

| model | accepted drafts | send plans | send outcome differs from the scenario's expected_send | expected claims missing |
|---|---|---|---|---|
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | 72 | 57 | 0 | 0/384 (0.0%) |
| `us.anthropic.claude-sonnet-4-6` | 72 | 57 | 0 | 0/384 (0.0%) |

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
