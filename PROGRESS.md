# PROGRESS.md

Last updated: 2026-11-09 (America/Santo_Domingo)
Current task: none (T-002 done; next: T-003)

## Completed
- T-001: public repository with an MIT license. `LICENSE` and the repo guides are on `main` and `.env` is untracked (checked locally). Public visibility and the About license were confirmed by the author; `gh` was not available to check them.
- T-002: sandbox spike run with `scripts/spike_sandbox.py`. Decision: go (ADR-007). The "adjudicates" criterion was not met; see below.

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

## In progress
Nothing.

## Verification
- `python3 -m py_compile scripts/spike_sandbox.py`: passed.
- Install command in AGENTS.md: ran successfully (`requests` 2.34.2, `python-dotenv` 1.2.4 installed in `.venv`).
- Sandbox runs: see the table above. No unit tests exist yet.
- Not run: `require-evidence`, `send-message --format multipart`.

## Blockers
- Open items to decide: Bedrock model ID, AWS credentials setup.
- T-002 changes are not committed yet; per the git workflow they need a commit and a PR to `main`.

## Next steps
1. Commit the T-002 changes on `feat/t-002-sandbox-spike` and open a PR (when the author asks).
2. Start T-003 (PayPal REST client); confirm or replace the provisional `requests` / `python-dotenv` dependencies.

## Resume instruction
Read AGENTS.md and TASKS.md, confirm the current state, then continue with T-003.
