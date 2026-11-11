# PROGRESS.md

Last updated: 2026-11-11 (America/Santo_Domingo)
Current task: T-008 README, license check and secrets scan (README written; secrets scan next)

## Completed
- T-001: public repository with an MIT license. `LICENSE` and the repo guides are on `main` and `.env` is untracked (checked locally). Public visibility and the About license were confirmed by the author; `gh` was not available to check them.
- T-002: sandbox spike run with `scripts/spike_sandbox.py`. Decision: go (ADR-007). The "adjudicates" criterion was not met; see below.
- T-003: PayPal REST client in `dispute_defender/paypal/`, offline tests, and a live smoke check with `scripts/smoke_client.py`. Results below.
- T-004: claim schema and deterministic verifier in `dispute_defender/claims/` (ADR-008), offline tests, and a live read-only check with `scripts/smoke_verifier.py` on two sandbox disputes. Results below.
- T-005: Bedrock drafter in `dispute_defender/drafter/` (ADR-009), offline tests, and three live happy-path runs with `scripts/smoke_drafter.py`. Results below.
- T-006: approval page and send in `dispute_defender/response/` and `dispute_defender/web/` (ADR-010), offline tests, and a live dry run and live send in Chrome on a new sandbox dispute. Results below.
- T-007: small evaluation on 24 **simulated** scenarios (ADR-011): live Part A (144 Bedrock calls) and offline Part B (fault injection). Results below.
- T-010: replay mode (ADR-012), three simulated disputes behind the `--replay` flag. Offline tests, a local run with curl, and the author's browser check. Merged in PR #9. Results below.

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
T-008: README, license check and secrets scan, on branch `docs/t-008-readme`.
- Commit 1: `README.md`. The sections are: what it is, with a headline result labelled simulated; replay mode; evaluation results (simulated); how it works; running against the sandbox; sandbox notes and limitations; Disputes API feedback; structure; license. Every evaluation number is copied from `evaluation/results.md`. The Part B per-group rows were checked to sum to 1,065 (1,192 with the merchant-record, benign and local-date cases). Code checked: Approve calls the model again (`web/app.py:274`), so the README says each Draft and each Approve is one billed call. Each feedback point names the dispute and step from this file where it was seen. Screenshot spots are HTML comment placeholders, and the video link is a TODO. No code or tests were changed.
- Fresh-clone check (author, 2026-11-11), replay only: the author cloned `docs/t-008-readme` into a temp directory, created a venv on Python 3.14.7, ran `pip install -r requirements.txt` (no errors) and `python -m dispute_defender.web --replay`, and the disputes list loaded. The README's dispute walkthrough was not part of this check.
- Not checked in a fresh clone: the sandbox-credentials path (`.env` from `.env.example`, dry run, live send).
- Secrets scan done (see Verification, T-008): no secrets found.
- Next: the author sets the license in GitHub About; screenshots and the video link in the README; then the PR. The sandbox-credentials path in a fresh clone is still unchecked.

## T-010 replay mode results
Decisions: ADR-012. Data, sources and what to type: `dispute_defender/replay/README.md`.

Delivered:
- `dispute_defender/replay/`: `data/replay.json` (three **simulated** disputes, each with source labels), `data.py` (loader; refuses data not labelled `"simulated": true`, a dispute without a source, a dispute that fails the app's `Dispute` model or an output that fails `DraftOutput`), `paypal.py` (`ReplayPayPalClient`: list, get, provide-evidence kept in memory, hand-written `UNDER_REVIEW` read-back, 422 without the link), `model.py` (`ReplayModelClient`: the dispute's output as a `submit_claims` call, found by the prompt's transaction ID), `README.md`.
- `web/app.py`: a third mode, `replay`, which requires both replay clients; replay clients are refused in dry and live mode. In replay mode Approve hands the evidence to the replay client. `web/__main__.py`: `--replay` flag; no `.env`, no real clients, `DISPUTE_DEFENDER_SEND_MODE` ignored. `web/settings.py`: `AppMode`; `load_send_mode()` unchanged (dry or live only).
- Templates: a blue REPLAY banner, replay wording in place of the PayPal read wording, and a source box per dispute (`_replay.html`). Dry and live pages render the same text as before: the offline UI preview was rendered before and after the change and compared with CSS and whitespace removed (13 of 13 pages identical); only CSS was added.

Replay disputes:
| Dispute | Data | Model output | Result |
|---|---|---|---|
| `PP-R-SIM-N1` | scenario N1, unchanged | recorded (N1, Sonnet 4.6, repetition 1) | 6 VERIFIED, approve records the payload, replayed `UNDER_REVIEW` |
| `PP-R-SIM-REPLAY2` | hand-written, `WAITING_FOR_BUYER_RESPONSE`, no link | none | refused before any model call |
| `PP-R-SIM-REPLAY3` | hand-written from N2, own transaction ID, no `seller_protection_eligible` | recorded N2 output, transaction ID adapted, amount 250.00 injected | amount BLOCKED, seller protection FLAGGED, 4 VERIFIED; neither reaches the payload |

Checks:
- 44 new offline tests in `tests/test_replay_data.py`, `tests/test_replay_clients.py`, `tests/test_replay_web.py` and `tests/test_replay_main.py`: provenance against `evaluation/scenarios/` and `evaluation/results/raw-2026-11-11.jsonl`; no real IDs, UUIDs, request IDs, emails or names beyond the `FAKE-...` placeholders; sockets blocked for the whole web flow; the REPLAY banner on every page including the 400, 403, 422 and PayPal error pages; BLOCKED and FLAGGED values never in the recorded payload; the recorded payload equals what `prepare_send` builds independently; a wrong tracking number or a hash mismatch records nothing; no environment variable or `.env` line enables replay; the flag never reads `.env` or builds a real client; mixed clients are refused; dry and live preview pages carry no replay text.
- No existing test was edited.
- Local run (2026-11-11): `python -m dispute_defender.web --replay --port 8765` under uvicorn, driven with curl and the browser's `Origin` header: dispute 1 draft 6 VERIFIED, approve showed the replay result and `UNDER_REVIEW`; dispute 3 draft 4 VERIFIED, 1 BLOCKED, 1 FLAGGED; dispute 2 refused.
- The author's check in a browser: done (reported by the author, 2026-11-11). Merged in PR #9.

Limits: no PayPal response in replay is a recording; model outputs are rebuilt from recorded claim values, not raw tool input, and dispute 3's is altered on purpose; no model variation, latency, tokens or API errors; the read-back is hand-written from the T-006 observation; dispute 2's refusal uses the real gate's wording ("PayPal does not offer provide-evidence ..."), where "PayPal" means the replay data; state is in memory and resets on restart.

## T-007 evaluation results
**All data is simulated. These numbers describe 24 simulated scenarios written for this evaluation; they do not describe real-world accuracy.** Source: `evaluation/results.md` (generated by `scripts/run_evaluation.py report`). Scoring definitions: ADR-011.

Delivered:
- ADR-011 (scoring definitions).
- `evaluation/scenarios/`: 24 simulated scenarios in 9 categories, each labelled `"simulated": true`, with ground truth for all six claim types. Authored for this evaluation with a throwaway script outside the repo, then checked by hand and by `tests/test_eval_scenarios.py`.
- `dispute_defender/evaluation/`: loader, pipeline (the real verifier and send gate), scoring and metrics, Part B fault injection, scripted fake clients, runner (cap, abort, resume), freeze hashes, report.
- `scripts/run_evaluation.py` with `faults`, `freeze`, `run` (`--dry-run` / `--confirm-spend`) and `report`.
- `evaluation/frozen.json` (freeze at 2026-11-11T03:57:46+00:00), `evaluation/DECLARED_CHANGES.md` (none declared), `evaluation/results/raw-2026-11-11.jsonl` (144 raw lines), `evaluation/results/faults.json` (Part B), `evaluation/results.md`.

Freeze: scenarios, scoring rules, prompt and pipeline were frozen at 03:57:46 UTC, before the first live call at 04:08:13 UTC, and all 144 calls ran with the frozen hashes. No change was declared after seeing results.

Part A, live, run by the author on 2026-11-11 (run window 04:08:13 to 04:11:33 UTC), `us.anthropic.claude-sonnet-4-6` and `us.anthropic.claude-haiku-4-5-20251001-v1:0`, 24 scenarios x 3 repetitions each:

| Metric | Sonnet 4.6 | Haiku 4.5 |
|---|---|---|
| Calls / accepted / rejected / errors | 72 / 72 / 0 / 0 | 72 / 72 / 0 / 0 |
| Model errors (M1) | 0/390 | 0/390 |
| Incorrect claims sent with no verifier (M2, counterfactual) | 6 (all R2, unsupported; see below) | 6 (all R2, unsupported; see below) |
| Incorrect claims VERIFIED / in a send plan (M3) | 0 / 0 | 0 / 0 |
| Correct claims wrongly rejected (M4) | 0/384 | 0/384 |
| Drafts rejected before the verifier (M5) | 0 | 0 |
| Scenarios identical across the 3 repetitions (M6) | 24/24 | 24/24 |
| Disagreements between ground truth and verifier (M7) | 0 | 0 |
| Tokens in / out | 144,990 / 15,635 | 144,918 / 17,787 |

How to read it:
- **M2 = 6 is one scenario**, R2 (a merchant record belonging to another transaction), x 3 repetitions x 2 claims (tracking number and carrier). These claims are `unsupported`, not model value errors: the model never sees the record's transaction ID, so it copied what the prompt showed. The verifier FLAGGED all 6 and none reached a send plan. M2 is computed from the same outputs (not a separate experiment) and keeps schema validation, so it is conservative.
- Outputs were identical across the 3 repetitions in all 24 scenarios, so the effective sample is **24 distinct cases per model**, not 72.
- Prompt injection (I1-I3): neither model claimed a manipulated value (1000.00 USD, another transaction ID, seller protection true, tracking 999, the fake record's tracking or UPS). This holds only for these simulated scenarios and author-written injections.
- No dollar cost is recorded in the repo (no prices were passed).

Part B, offline (1,192 fault cases on 24 scenarios):
- 1,065 deliberately altered claims (amount, date, transaction ID, seller protection, tracking and carrier, source and type, tool input), 1,065 caught. Expected by construction: the faults were written against known rules.
- Known blind spot: an altered merchant record, 0 of 43 caught, and 20 of them reached a send plan. The verifier trusts the merchant record.
- Equivalent values: 82 of 82 VERIFIED. Correct local dates near midnight (D1, D2): 2 of 2 BLOCKED by design (UTC rule, ADR-008). Baseline: 0 of 128 correct claims rejected.

Found and fixed while building (before the freeze and before any live call):
- A fault operator turned carrier `FedEx` into `FedEX`, a case variant the verifier correctly accepts; it showed as 3 false "misses". The operator now changes a letter to a different letter ignoring case, and a test checks that every value fault differs from all accepted values.
- The dry-run token heuristic first used 3 characters per token; it is 2.3 now, documented in `runner.py`. Observed input was about 2,013 tokens per call (144,990 / 72 for Sonnet), close to the estimate of about 2,142 per call.

Checks on the committed results (2026-11-11): the raw JSONL, `results.md` and `faults.json` hold no prompt text, no buyer-message text, no credentials and no real PayPal IDs (scanned for prompt and buyer-message markers, `FAKE-BUYER`, the sandbox dispute and transaction IDs from T-002 to T-006, AWS key patterns, and the PayPal client ID and secret without printing them). The raw lines do hold Bedrock request IDs (UUIDs) and the model's claim values, which come from the simulated scenarios.

Limits (full list in `results.md`): simulated scenarios written with knowledge of the verifier's rules; one dispute reason; 24 distinct cases per model; zero observed errors does not mean a zero error rate; two models, one run window; the verifier cannot catch a wrong merchant record; nothing here says whether a response would win a dispute.

## Verification
- T-008 secrets scan (2026-11-11). Method: gitleaks and trufflehog are not installed, so a local Python regex script outside the repo (nothing installed) printed pattern names, counts and paths only; no matched value was printed or written. Scope:
  - The working tree: tracked files plus untracked files that are not gitignored, skipping `.venv`, `.pytest_cache` and `__pycache__`; the ignored local `.env` was read only to take the PayPal client ID and secret as literals to search for.
  - The full history: all 54 commits on all 14 refs, including every blob reachable from them (so deleted files too) and every commit message.
  - Commit metadata: author and committer emails.

  Results:
  | Pattern | Working tree | History | Classification |
  |---|---|---|---|
  | PayPal client ID / secret, literal values from `.env` | 0 | 0 | none |
  | `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` assigned a 20+ character value | 1 match, `.env.example` | 4 matches, `.env.example` | False positive: the regex matched across a line break. Both values are empty in all 7 versions of `.env.example` in history; a same-line rerun gave 0 |
  | AWS access key ID (`AKIA` / `ASIA`) | 0 | 0 | none |
  | `aws_secret_access_key` assigned a 40-character key-like value | 0 | 0 | none |
  | Any `aws_secret` text | 3 files | 3 files (same) | Benign. `tests/conftest.py`: the env var name, in the list of AWS variables the tests clear. `tests/test_bedrock_client.py`: the fake `"testing"` key for botocore's Stubber. `tests/test_replay_data.py`: the name inside a regex that asserts the replay data contains no secrets |
  | Private key block | 0 | 0 | none |
  | Bearer token (20+ characters) | 0 | 0 | none |
  | Basic token (16+ characters) | 0 | 0 | none |
  | Email, placeholder domain (`example.*`, `.invalid`, `.test`) | 34 matches in 31 files | 37 matches in 31 files | Benign: fake buyer and seller addresses in `evaluation/scenarios/*.json` (24), `dispute_defender/replay/data/replay.json`, `tests/fixtures/paypal/*.json` (3), `tests/conftest.py`, `tests/test_eval_scenarios.py`, `tests/test_models.py`, `tests/test_replay_data.py` |
  | Email, other | 1, `tests/test_config.py` | 1, same | Benign: not an address. A URL with placeholder userinfo (`user:` plus a 2-letter placeholder password) in a host-guard test that must be refused |
  | Email, co-author attribution | 0 | 84, commit messages only | Benign: the Claude co-author trailer |
  | Email equal to the author's git `user.email` | 0 | 0 | none in file content or messages |
  | Author's local home path (`/Users/<name>` or `/home/<name>`) | 0 | 0 | none |
  | Author's local username | 0 | 0 | none |
  | `.env` files ever added, on any ref | `.env.example` only | `.env.example` only | No `.env` was ever committed; `.env` is ignored and untracked |
  | Commit metadata emails | n/a | 2 distinct | Both are noreply addresses: the author's GitHub noreply form and GitHub's merge committer address |

  Not in scope: the GitHub handle in the clone URL in `README.md`. It is intentional (author decision) and was not counted as a finding.
- T-010 (2026-11-11): `.venv/bin/python -m pytest`: 714 passed, offline, one warning (the Starlette `httpx` notice); 44 of them added in T-010. Secret scan on the working tree and git history (AWS access key IDs, AWS secret key names, AWS ARNs, 12-digit account-like numbers, and the PayPal client ID and secret from `.env` matched without printing them): no secrets; the only secret-key-name matches are the same two as in T-005. `.env` is ignored and untracked. Local replay server run with curl: see the T-010 section.
- T-007 close (2026-11-11): `.venv/bin/python -m pytest`: 670 passed, offline, one warning (the Starlette `httpx` notice). Secret scan on the working tree (including the untracked raw results) and git history (AWS access key IDs, AWS secret key names, AWS ARNs, 12-digit account-like numbers, and the PayPal client ID and secret matched without printing them): no secrets; the only secret-key-name matches are the same two as in T-005 (`tests/conftest.py`, `tests/test_bedrock_client.py`). `.env` is ignored and untracked.
- T-007: live Part A run by the author on 2026-11-11 with `scripts/run_evaluation.py run --confirm-spend` (144 calls, 0 errors), then `report`; see the T-007 section.
- T-007: `.venv/bin/python -m pytest`: 670 passed, offline (2026-11-10); 224 of them added in T-007. One warning: the Starlette `httpx` notice. No Bedrock or PayPal call was made.
- T-007: `scripts/run_evaluation.py faults`, `freeze`, `report` and `run --dry-run` ran offline (results above).
- T-007: secret scan on the working tree and git history (AWS access key IDs, AWS secret key names, AWS ARNs, 12-digit account-like numbers, and the PayPal client ID and secret from `.env` matched without printing them): no secrets. The only secret-key-name matches are the same two as in T-005 (`tests/conftest.py`, `tests/test_bedrock_client.py`). `.env` is ignored and untracked.
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
1. T-008: README written (commit 1). Remaining: the secrets scan on the working tree and full history (commit 2), a fresh-clone check, screenshots and the video link in the README, the license in About (author), then the PR.
2. T-009: demo video (under 3 minutes) and submission.
3. Optional, only if time remains: the live prompt-injection run (T-005), T-011 (401 retry), T-012 (cosmetic fixes).

## Resume instruction
Read AGENTS.md and TASKS.md, confirm the current state, then continue T-008 on `docs/t-008-readme` (secrets scan after the author confirms).
