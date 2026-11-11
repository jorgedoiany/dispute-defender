# PROGRESS.md

Last updated: 2026-11-10 (America/Santo_Domingo)
Current task: T-007 (small evaluation)

## Completed
- T-001: public repository with an MIT license. `LICENSE` and the repo guides are on `main` and `.env` is untracked (checked locally). Public visibility and the About license were confirmed by the author; `gh` was not available to check them.
- T-002: sandbox spike run with `scripts/spike_sandbox.py`. Decision: go (ADR-007). The "adjudicates" criterion was not met; see below.
- T-003: PayPal REST client in `dispute_defender/paypal/`, offline tests, and a live smoke check with `scripts/smoke_client.py`. Results below.
- T-004: claim schema and deterministic verifier in `dispute_defender/claims/` (ADR-008), offline tests, and a live read-only check with `scripts/smoke_verifier.py` on two sandbox disputes. Results below.
- T-005: Bedrock drafter in `dispute_defender/drafter/` (ADR-009), offline tests, and three live happy-path runs with `scripts/smoke_drafter.py`. Results below.
- T-006: approval page and send in `dispute_defender/response/` and `dispute_defender/web/` (ADR-010), offline tests, and a live dry run and live send in Chrome on a new sandbox dispute. Results below.

## T-002 spike results
All calls went to `api-m.sandbox.paypal.com`. Sandbox IDs: order `6HK11753C5145591C`, capture `54X87564PT289050U`, dispute `PP-R-HBV-10197617` (reason `MERCHANDISE_OR_SERVICE_NOT_RECEIVED`, 10.00 USD). Every dispute action also read the dispute before and after the call; all of those reads returned HTTP 200. Link names are shown as printed by the script, with underscores turned into hyphens.

Steps in the order they ran:

| # | Step | HTTP | Result |
|---|---|---|---|
| 1 | `token` | 200 | Token obtained; disputes scopes `read-seller` and `update-seller` granted |
| 2 | `create-order` | 200 | Order `PAYER_ACTION_REQUIRED`; buyer approved it in the browser (manual) |
| 3 | `capture` | 201 | Order and capture `COMPLETED`, 10.00 USD; buyer then opened an "item not received" case in the sandbox Resolution Center (manual) |
| 4 | `list` | 200 | 0 disputes (shortly after the case was opened) |
| 5 | `list` | 200 | 1 dispute: `WAITING_FOR_SELLER_RESPONSE`, stage `INQUIRY` |
| 6 | `show` | 200 | Links: accept-claim, escalate, make-offer, provide-evidence, self, send-message |
| 7 | `provide-evidence` (stage `INQUIRY`) | 200 | Accepted. After: `UNDER_REVIEW`, `INQUIRY`, links: self |
| 8 | `adjudicate` #1 (`SELLER_FAVOR`) | 400 | Refused: `ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE`, debug_id `f41195223259c`. Before: `WAITING_FOR_BUYER_RESPONSE`, `INQUIRY`; no adjudicate link |
| 9 | `send-message` (JSON) | 200 | Accepted. State unchanged: `WAITING_FOR_BUYER_RESPONSE`, `INQUIRY` |
| 10 | `escalate` | 200 | Accepted. After: `UNDER_REVIEW`, stage still `INQUIRY`, links: self |
| 11 | `adjudicate` #2 (`SELLER_FAVOR`) | 400 | Refused: `ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE`, debug_id `f5762566c41ef`. Before: `UNDER_REVIEW`, `INQUIRY`; no adjudicate link |
| 12 | `show` | 200 | `WAITING_FOR_SELLER_RESPONSE`, stage `CHARGEBACK`, links: accept-claim, provide-evidence, self |
| 13 | `provide-evidence` (stage `CHARGEBACK`) | 200 | Accepted. After: `UNDER_REVIEW`, `CHARGEBACK`, links: provide-supporting-info, self |
| 14 | `adjudicate` #3 (`SELLER_FAVOR`) | 400 | Refused: `ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE`, debug_id `f122443e37da0`. Before: `UNDER_REVIEW`, `CHARGEBACK`; no adjudicate link |
| - | `require-evidence` | not called | PayPal never offered the require-evidence link |

Observations:
- Statuses change on their own. After step 7 the status was `UNDER_REVIEW`; by step 8 it was `WAITING_FOR_BUYER_RESPONSE` with no call in between. `UNDER_REVIEW` was short-lived after the first evidence submission.
- After `escalate` was accepted, the stage still read `INQUIRY` at 17:35, and it read `CHARGEBACK` at 21:52 (America/Santo_Domingo). The author was away from the spike between those times, so how long PayPal takes to reflect an escalation is unknown.
- `send-message` worked with a JSON body, although the API spec lists only multipart. The multipart form was not tried.
- Evidence (`PROOF_OF_FULFILLMENT` with PayPal's documented placeholder tracking number) was accepted without a file, at both stages.
- `provide-supporting-info` appeared as a new link after the second evidence submission. It was not tested.
- `accept-claim` was offered several times and never called.
- `adjudicate` was refused in every state tried, including `UNDER_REVIEW` in the `CHARGEBACK` stage, and its link never appeared.
- "Accepted by PayPal" (HTTP 200) means PayPal accepted the submission. It does not show that the evidence would win a real case.
- An error with issue `ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE` arrives as HTTP 400 with the generic name `INVALID_REQUEST`; the issue code is the useful part.

## T-003 client results
Delivered:
- `dispute_defender/paypal/` (config, errors, models, client), offline tests in `tests/`, `scripts/smoke_client.py`, pinned `requirements.txt` and new `requirements-dev.txt`, AGENTS.md Structure and Commands, `.env.example` PayPal names confirmed. `scripts/spike_sandbox.py` is unchanged.
- Dependencies: `requests` and `python-dotenv` kept (the client uses `requests`; the spike, smoke script and future app entry point load `.env` with `python-dotenv`). Added `pydantic` 2.14.3 (pydantic-core 2.50.4), installed and checked on Python 3.14.7 before it was used. Test-only: `pytest` 9.2.0, `responses` 0.26.3.

Live smoke check, all against `api-m.sandbox.paypal.com`, one step per run, each with the author's go-ahead. The smoke script prints `OK` instead of the HTTP status; the client raises on any non-2xx, so `OK` means a 2xx response that passed validation. The exact codes were not printed. Every run exited 0. The new dispute `PP-R-KXL-10197854` (reason `MERCHANDISE_OR_SERVICE_NOT_RECEIVED`, 10.00 USD) was opened manually by the author as the sandbox buyer and reserved for the write steps.

| # | Step | Result |
|---|---|---|
| 1 | `token` | OK. Disputes scopes `read-seller` and `update-seller` granted |
| 2 | `list` | OK. 2 disputes: `PP-R-KXL-10197854` `WAITING_FOR_SELLER_RESPONSE`/`INQUIRY`; `PP-R-HBV-10197617` `UNDER_REVIEW`/`CHARGEBACK` |
| 3 | `show PP-R-KXL-10197854` | OK. `WAITING_FOR_SELLER_RESPONSE`, `INQUIRY`, links: accept-claim, escalate, make-offer, provide-evidence, self, send-message |
| 4 | `show PP-R-HBV-10197617` | OK. `UNDER_REVIEW`, `CHARGEBACK`, links: accept-claim, provide-supporting-info, self (read only; no action called) |
| 5 | `provide-evidence PP-R-KXL-10197854` (stage `INQUIRY`, placeholder tracking) | Accepted. Before: `WAITING_FOR_SELLER_RESPONSE`. After: `UNDER_REVIEW`, `INQUIRY`, links: self |
| 6 | `show PP-R-KXL-10197854` | OK. `UNDER_REVIEW`, `INQUIRY`, links: self |
| 7 | `show PP-R-KXL-10197854` (later, no call in between) | OK. `WAITING_FOR_BUYER_RESPONSE`, `INQUIRY`, links: accept-claim, escalate, self, send-message |
| 8 | `send-message PP-R-KXL-10197854` (JSON, labelled test message) | Accepted. Before and after: `WAITING_FOR_BUYER_RESPONSE`, `INQUIRY`, links unchanged |
| 9 | `show PP-R-KXL-10197854` | OK. Unchanged from step 8 |

Top-level keys of the dispute JSON, as observed (names only). These are observations from two sandbox disputes, not rules about PayPal's schema:
- Present in every read (steps 3, 4, 6, 7, 9): `create_time`, `dispute_amount`, `dispute_channel`, `dispute_id`, `dispute_life_cycle_stage`, `dispute_state`, `disputed_transactions`, `evidences`, `extensions`, `fund_movements`, `links`, `messages`, `offer`, `reason`, `refund_details`, `status`, `update_time`.
- `allowed_response_options`: present in `WAITING_FOR_SELLER_RESPONSE`/`INQUIRY` (step 3), `UNDER_REVIEW`/`CHARGEBACK` (step 4) and `WAITING_FOR_BUYER_RESPONSE`/`INQUIRY` (steps 7, 9); absent in `UNDER_REVIEW`/`INQUIRY` (step 6).
- `seller_response_due_date`: present only in `WAITING_FOR_SELLER_RESPONSE`/`INQUIRY` (step 3).
- `buyer_response_due_date`: present only in `WAITING_FOR_BUYER_RESPONSE`/`INQUIRY` (steps 7, 9).

Observations:
- The same pattern as T-002: evidence moved the status to `UNDER_REVIEW` with only the self link, and PayPal moved it to `WAITING_FOR_BUYER_RESPONSE` on its own a few minutes later. `send-message` did not change status or links.
- Real responses passed the client's validation, including list items and link names (the client treats `send_message` and `send-message` as the same).
- Transaction details are under `disputed_transactions`. At the time of T-003 they were not in the models (out of scope until T-004); T-004 extended the models with the seller-side transaction fields the verifier needs.

## T-004 claim verifier results
Discovery: `scripts/smoke_client.py show --nested-keys` (new flag) was run once on each sandbox dispute, read only, with the author's go-ahead. Both exited 0. Key names only; these are observations from two disputes, not rules about PayPal's schema.

| Dispute | Status / stage | Links |
|---|---|---|
| `PP-R-KXL-10197854` | `WAITING_FOR_BUYER_RESPONSE` / `INQUIRY` | accept-claim, escalate, self, send-message |
| `PP-R-HBV-10197617` | `UNDER_REVIEW` / `CHARGEBACK` | accept-claim, provide-supporting-info, self |

Same nested key names on both:
- `disputed_transactions[0]`: `buyer`, `buyer_transaction_id`, `create_time`, `gross_amount`, `items`, `seller`, `seller_protection_eligible`, `seller_protection_type`, `seller_transaction_id`, `transaction_status`
- `evidences[0]`: `date`, `dispute_life_cycle_stage`, `evidence_type`, `notes`, `source`
- `messages[0]`: `content`, `posted_by`, `time_posted`
- `offer`: `buyer_requested_amount`

Delivered:
- `dispute_defender/paypal/models.py`: `DisputedTransaction` (seller-side fields only, all optional) and `Dispute.transactions`.
- `dispute_defender/claims/`: `Claim`, `MerchantOrderRecord`, `Verdict`, `ClaimResult`, `verify_claim()`, `verify_claims()`. Rules in ADR-008 and the verifier docstring.
- `scripts/smoke_client.py show --nested-keys` and the new read-only `scripts/smoke_verifier.py`.
- `tests/test_verifier.py` (new), `tests/test_models.py` (transaction fields). The `dispute_inquiry_waiting.json` fixture has placeholder transaction values, labelled in the fixtures README.

Live verifier check with `scripts/smoke_verifier.py`, 2026-11-10, read only, one dispute per run with the author's go-ahead; both runs exited 0. The claims were written by the author as fixed test values; none were generated by a model. Merchant record used in both runs (a test record, not a real order): `transaction_id` set to the dispute's transaction, `tracking_number` `122533485`, `carrier` `FedEx`. "Not stated" means the author gave no expected verdict.

Dispute `PP-R-KXL-10197854`, transaction `9J725035KE512071R` (`WAITING_FOR_BUYER_RESPONSE` / `INQUIRY`):

| # | Claim (source) | Expected | Actual |
|---|---|---|---|
| 1 | transaction_id `9J725035KE512071R` (paypal) | VERIFIED | VERIFIED |
| 2 | amount 10.00 USD (paypal) | VERIFIED | VERIFIED |
| 3 | transaction_date `2026-11-10` (paypal) | VERIFIED | VERIFIED (PayPal UTC date `2026-11-10`) |
| 4 | transaction_date `2026-11-09` (paypal) | BLOCKED | BLOCKED (UTC rule) |
| 5 | amount 12.00 USD (paypal) | BLOCKED | BLOCKED (value 12.00 vs 10.00) |
| 6 | tracking_number `122533485` (merchant_record) | VERIFIED | VERIFIED |
| 7 | carrier `fedex` (merchant_record) | VERIFIED | VERIFIED (record `FedEx`) |
| 8 | tracking_number `000` (merchant_record) | BLOCKED | BLOCKED |
| 9 | seller_protection `true` (paypal) | not stated | VERIFIED |

Dispute `PP-R-HBV-10197617`, transaction `54X87564PT289050U` (`UNDER_REVIEW` / `CHARGEBACK`):

| # | Claim (source) | Expected | Actual |
|---|---|---|---|
| 1 | transaction_id `54X87564PT289050U` (paypal) | VERIFIED | VERIFIED |
| 2 | amount 10.00 USD (paypal) | VERIFIED | VERIFIED |
| 3 | transaction_date `2026-11-09` (paypal) | VERIFIED | VERIFIED (PayPal UTC date `2026-11-09`) |
| 4 | transaction_date `2026-11-10` (paypal) | BLOCKED | BLOCKED (UTC rule) |
| 5 | amount 12.00 USD (paypal) | BLOCKED | BLOCKED (value 12.00 vs 10.00) |
| 6 | tracking_number `122533485` (merchant_record) | VERIFIED | VERIFIED |
| 7 | carrier `fedex` (merchant_record) | VERIFIED | VERIFIED (record `FedEx`) |
| 8 | tracking_number `000` (merchant_record) | BLOCKED | BLOCKED |
| 9 | seller_protection `true` (paypal) | not stated | VERIFIED |

Stated expectations met: 8/8 on each dispute. `smoke_client.py show` was also run on both disputes after the change (exit 0); state and links were unchanged from the discovery table above.

Observations:
- Live responses on both disputes passed the extended `Dispute` model: `create_time` carried a timezone, `gross_amount` parsed as money and `seller_protection_eligible` was a JSON boolean. One sample per dispute; the exact value formats were not printed.
- Both transactions are 10.00 USD and both were reported seller-protection eligible. `transaction_status` is parsed but no rule reads it.
- FLAGGED did not come up live; it is covered by offline tests only.
- `evidences[0]` has no key that holds the submitted tracking info (keys observed: `date`, `dispute_life_cycle_stage`, `evidence_type`, `notes`, `source`). A read-back after sending can therefore confirm that evidence exists, not its content.
- The verdicts show the verifier works on live sandbox data. They say nothing about whether a real dispute would be won.

## T-005 drafter results
Prerequisites (ADR-003): region `us-east-1`; primary `us.anthropic.claude-sonnet-4-6`, secondary `us.anthropic.claude-haiku-4-5-20251001-v1:0`; auth through the AWS CLI default profile and the boto3 credential chain. Not available to this account on 2026-11-10: `us.anthropic.claude-sonnet-5`, `us.anthropic.claude-sonnet-5-5`, `us.anthropic.claude-haiku-5-5` (`AccessDeniedException`); `us.anthropic.claude-sonnet-4-5-20250929-v1:0` (Legacy).

Delivered:
- `boto3` 1.44.0 (botocore 1.44.0), pinned and checked on Python 3.14.7.
- `Dispute.messages` (`posted_by`, `content`), excluded from `model_dump` and `repr`.
- `dispute_defender/drafter/`: output schema and `submit_claims` tool spec, prompt builder (fact allowlist, untrusted buyer-message block), `ModelClient` interface, `BedrockModelClient`, `draft_claims()` with output validation. Design in ADR-009.
- `scripts/smoke_drafter.py`.
- Offline tests: `tests/test_drafter_schema.py`, `tests/test_drafter_prompt.py`, `tests/test_bedrock_client.py` (botocore Stubber), `tests/test_drafter.py` (fake client, including prompt-injection cases), plus new `Dispute.messages` tests in `tests/test_models.py`. The Bedrock fixture is hand-written and labelled.

Live runs, 2026-11-10, run by the author with `scripts/smoke_drafter.py` against the PayPal sandbox (GET only) and Bedrock `us-east-1`, with the fixed test merchant record. Nothing was sent to PayPal. Results as reported by the author:

| # | Model | Dispute (stage / status) | Stop | Tokens in / out | Schema | Claims | Verdicts |
|---|---|---|---|---|---|---|---|
| 1 | primary `us.anthropic.claude-sonnet-4-6` | `PP-R-KXL-10197854` (`INQUIRY` / `WAITING_FOR_BUYER_RESPONSE`) | `tool_use` | 2024 / 267 | OK | 6 | 6 VERIFIED |
| 2 | primary `us.anthropic.claude-sonnet-4-6` | `PP-R-HBV-10197617` (`CHARGEBACK` / `UNDER_REVIEW`) | `tool_use` | 2015 / 266 | OK | 6 | 6 VERIFIED |
| 3 | secondary `us.anthropic.claude-haiku-4-5-20251001-v1:0` | `PP-R-KXL-10197854` (`INQUIRY` / `WAITING_FOR_BUYER_RESPONSE`) | `tool_use` | 2023 / 267 | OK | 6, identical to run 1 | 6 VERIFIED |

Observations:
- Both models accepted the forced `toolChoice` and the generated schema (a discriminated union with `$ref`s inlined); no flattening was needed. This is verified only for these two models.
- The live runs are happy-path runs with a fixed test merchant record. They show the pipeline works end to end; they do not measure model accuracy (T-007).
- Invalid-output rejection cannot be forced live; it is evidenced by offline tests only.
- The optional live prompt-injection run was not done. FLAGGED did not come up live.

## T-006 approval page and send results
Delivered:
- `dispute_defender/response/`: `render_notes()` (fixed template from VERIFIED claims only, canonical carrier), `prepare_send()` send gate, the fixed carrier list (`FEDEX` only).
- `dispute_defender/web/`: FastAPI app with Jinja2 templates (autoescape on), single-use HMAC CSRF tokens, Origin and Host checks, security headers, safe error pages, the unknown-outcome page, and `python -m dispute_defender.web` on 127.0.0.1 only. Dry by default (`DISPUTE_DEFENDER_SEND_MODE`).
- `Dispute.response_option_names`: key names of `allowed_response_options`, shown for information, never a send condition.
- Dependencies, pinned and checked on Python 3.14.7: `fastapi` 0.162.4 (starlette 1.10.0), `jinja2` 3.1.6, `python-multipart` 0.0.33, `uvicorn` 0.54.0; dev `httpx` 0.28.1. Starlette warns that `httpx` with its TestClient is deprecated in favour of `httpx2`; the approved pin was kept.
- Offline tests: `tests/test_render.py`, `tests/test_send_gate.py`, `tests/test_web.py`, `tests/test_csrf.py`, plus `allowed_response_options` tests in `tests/test_models.py`.

Live runs, 2026-11-10 (America/Santo_Domingo; times below in UTC), run by the author in Chrome against the PayPal sandbox and Bedrock. Results as reported by the author.

1. **Real-browser bug.** The first Draft click was refused with 403 "Cross-origin request refused". Cause: the app sent `Referrer-Policy: no-referrer`, and with that policy Chrome sends `Origin: null` on the page's own form POSTs. The TestClient tests did not catch it. Fixed in `6ab9e33` with `Referrer-Policy: same-origin`; `null` and foreign origins are still refused (ADR-010 notes). The fix was reproduced and checked locally against uvicorn with a stubbed PayPal session and a fake model (no live calls) before the live runs.
2. **New dispute** `PP-R-UXH-10198605`, made with `scripts/spike_sandbox.py create-order`, buyer approval in the browser, `capture`, and an "item not received" case opened by the sandbox buyer. It read `UNDER_REVIEW` right after creation and `WAITING_FOR_SELLER_RESPONSE` / `INQUIRY` a few minutes later.
3. **Dry run** (default mode): Draft, then Approve. All 6 claims VERIFIED: 4 against PayPal data (transaction ID, amount, date, seller protection) and 2 against the test merchant record (tracking `122533485`, carrier `FEDEX`; a test record, not a real shipment). The pages showed the DRY RUN banner, the payload and the rendered text. The read-back was labelled "not changed by this run": still `WAITING_FOR_SELLER_RESPONSE` with the `provide-evidence` link.
4. **Live send** (`DISPUTE_DEFENDER_SEND_MODE=live`, LIVE SANDBOX SEND banner): Draft, then Approve. PayPal accepted provide-evidence: `PROOF_OF_FULFILLMENT` with the tracking info and the rendered text (about 300 characters) in `notes`. By design each Draft and each Approve is one billed Bedrock call, so 4 calls across the two runs.

State timeline of `PP-R-UXH-10198605`:

| When (UTC) | Source | Status / stage | Links |
|---|---|---|---|
| right after creation | `spike_sandbox.py` | `UNDER_REVIEW` | not recorded |
| a few minutes later, and through the dry run | `spike_sandbox.py` / app | `WAITING_FOR_SELLER_RESPONSE` / `INQUIRY` | includes provide-evidence |
| 02:14:36 | app read-back after the live send | `UNDER_REVIEW` / `INQUIRY` | self |
| 02:19:00 | app Refresh (`/state`) | `WAITING_FOR_BUYER_RESPONSE` / `INQUIRY` | accept-claim, escalate, self, send-message |

Observations:
- `allowed_response_options` held only `accept_claim` while the `provide_evidence` link was offered, and provide-evidence was then accepted. This confirms the gate on the link (ADR-010).
- Same pattern as T-002 and T-003: after evidence, `UNDER_REVIEW` with only the self link, then `WAITING_FOR_BUYER_RESPONSE` a few minutes later without any call from the app. The read-back and Refresh showed it as it happened.
- "Accepted by PayPal" means PayPal took the submission; it does not show the evidence would win a real case.
- Cosmetic, moved to T-012: status text wraps in the disputes table; the dry-run success message uses the red error border.

Not verified:
- PayPal's limit on `notes` length: the text sent was about 300 characters; the app's 2,000-character cap is an assumption.
- Carriers other than `FEDEX`.
- FLAGGED and BLOCKED claims in the app live: offline tests only.
- The content of submitted evidence: the API does not return it, so the read-back confirms the state, not what was stored.
- The unknown-outcome page (timeouts, dropped connections, 5xx): offline tests only.
- Concurrent requests, and browsers other than Chrome.

## In progress
- T-007: small evaluation on `feat/t-007-evaluation`. Scoring definitions in ADR-011.

## Verification
- T-006: `.venv/bin/python -m pytest`: 446 passed, offline (2026-11-10); 184 of them added in T-006. One warning: Starlette's deprecation notice for `httpx` with its TestClient. PayPal is mocked with `responses` and the model is a fake client.
- T-006: the Origin bug was reproduced and the fix checked against the real app under uvicorn on 127.0.0.1 with a stubbed PayPal session and a fake model: real origin 200, `Origin: null` 403, header `Referrer-Policy: same-origin`.
- T-006: live dry run and live send in Chrome: see the T-006 section.
- T-006: secret scan (AWS access key IDs, AWS secret key names, the PayPal client ID and secret matched without printing them, AWS ARNs, 12-digit account-like numbers, plus git history): no secrets. The only secret-key-name matches are the same two as in T-005.
- T-005: `.venv/bin/python -m pytest`: 262 passed, offline (2026-11-10); 115 of them added in T-005. Bedrock is never called in tests: botocore's Stubber or a fake client answers, and `tests/conftest.py` clears AWS env vars, hides the profile files and blocks botocore's HTTP send.
- T-005: `py_compile` and `--help` on `scripts/smoke_drafter.py` passed offline before the live runs; live runs: see the T-005 table.
- T-005: secret scan (AWS access key IDs, AWS secret key names, the PayPal client ID and secret matched without printing them, AWS ARNs, 12-digit account-like numbers, plus git history): no secrets. The only secret-key-name matches are an env var name in `tests/conftest.py` and a fake `"testing"` key in `tests/test_bedrock_client.py`.
- T-004: `.venv/bin/python -m pytest`: 147 passed, offline (2026-11-10).
- T-004: `py_compile` and `show --help` on `scripts/smoke_client.py` passed; the two live `show --nested-keys` runs are listed above.
- T-004: `py_compile` and `--help` on `scripts/smoke_verifier.py` passed; an offline dry run against the hand-written fixture met 8/8 expectations before the live runs.
- T-004: live verifier and show runs: see the T-004 tables.
- T-003: `.venv/bin/python -m pytest`: 69 passed, offline (every HTTP call mocked with `responses`; PAYPAL_* env vars cleared per test).
- T-003: `python -m py_compile` on both scripts passed; `scripts/smoke_client.py --help` runs. `git diff` shows no change to `scripts/spike_sandbox.py`.
- T-003: live smoke check: see the table above.
- T-002: `python3 -m py_compile scripts/spike_sandbox.py`: passed.
- T-002: install command in AGENTS.md ran successfully (`requests` 2.34.2, `python-dotenv` 1.2.4 installed in `.venv`).
- T-002 sandbox runs: see the T-002 table.
- Not run: `require-evidence`, `send-message --format multipart`, provide-evidence with a file.

## Blockers
- None.

## Next steps
1. T-007: small evaluation. About 20-30 disputes with seeded errors (wrong amount, date or tracking), simulated and labelled as simulated (ADR-007). Metric: wrong claims that reach the send step, model-only draft vs. draft with verifier. Write down the result and its limits.
2. T-008: README (what it does and the measured result first, then setup and run steps, the PayPal sandbox and model used, known limitations), a fresh-clone check, the secrets scan on the repo and history, and the license in the About section.
3. Optional, only if time remains: the live prompt-injection run (T-005), T-011 (401 retry), T-012 (cosmetic fixes).

## Resume instruction
Read AGENTS.md and TASKS.md, confirm the current state, then continue with T-007.
