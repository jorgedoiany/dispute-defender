# Dispute Defender

Dispute Defender helps a PayPal merchant answer an "item not received" dispute. An AI model drafts the response as structured claims, plain code checks every claim against PayPal API data or the merchant's own order record, and nothing is sent until the merchant approves. It runs against the **PayPal sandbox only**.

**Flow:** Claude on Amazon Bedrock drafts structured claims → deterministic code verifies each claim against PayPal dispute data or the merchant record → the merchant reviews and approves on a local web page → the evidence is sent to the PayPal sandbox (`provide-evidence`) → the dispute's new state is read back from PayPal and shown.

**Measured result (simulated data):** on 24 simulated scenarios, each model made 0 claim errors in 390 claims, and no incorrect claim was marked VERIFIED. Baseline comparison: without the verifier, 6 incorrect claims per model would have been sent, all from one simulated scenario where the merchant record belongs to another transaction (counted from the same model outputs). With the verifier, 0 reached a send plan. This is one scenario, not a rate. A wrong merchant record is not caught. See [Evaluation results](#evaluation-results-simulated-data). Accuracy on real disputes was not measured.

**Live sandbox run (a single run, T-006, 2026-11-11 UTC; the evening of 2026-11-10 in the Dominican Republic):** the full path ran once end to end on sandbox dispute `PP-R-UXH-10198605`. PayPal accepted the provide-evidence call. The state read back from PayPal was `UNDER_REVIEW` at 2026-11-11 02:14:36 UTC and `WAITING_FOR_BUYER_RESPONSE` at 2026-11-11 02:19:00 UTC, with no further write call from the app (the second reading came from a Refresh, which only reads). "Accepted" means PayPal took the submission; it does not show that the evidence would win a case.

First commit on 2026-11-09, after the submission period opened on 2026-10-01 (Devpost rules).

<!-- SCREENSHOT: draft-page-verdicts -->

## Try it without credentials (replay mode)

Replay mode runs the real app on local, **simulated** data. It needs no PayPal or AWS credentials and no network access.

```
git clone https://github.com/jorgedoiany/dispute-defender.git
cd dispute-defender
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m dispute_defender.web --replay
```

Open `http://127.0.0.1:8000`. Every page shows a blue **REPLAY** banner. Replay starts only with the `--replay` flag. With the flag, the app reads no `.env` file, builds no PayPal or Bedrock client and ignores `DISPUTE_DEFENDER_SEND_MODE`. The app was verified with Python 3.14.7; other versions were not tested.

| Dispute | What to type | What you see |
|---|---|---|
| `PP-R-SIM-N1` | tracking `SIM100000001`, carrier `FEDEX` | 6 claims VERIFIED. Approve records the evidence in memory; the replayed state is `UNDER_REVIEW` and a second response is refused |
| `PP-R-SIM-REPLAY2` | nothing (no form) | Refused: the dispute is waiting for the buyer and offers no `provide_evidence` link, so no model output is used |
| `PP-R-SIM-REPLAY3` | tracking `SIM100000002`, carrier `FEDEX` | Amount BLOCKED (a model error injected on purpose), seller protection FLAGGED, the other 4 VERIFIED. The response leaves both out and can still be approved |

Any other tracking number makes the verifier block the tracking claim, and then the send gate refuses the whole response.

What is simulated:
- Only the two external systems are swapped: a replay PayPal client and a replay model client. The prompt builder, drafter validation, verifier, renderer, send gate, CSRF checks and read-back are the real code.
- The disputes are hand-written and only shaped like sandbox data. None is a recording of a PayPal response, and none is a real dispute.
- The model outputs are rebuilt from claims that `us.anthropic.claude-sonnet-4-6` made on simulated scenarios in the evaluation run on 2026-11-11. In dispute 3 the amount was changed on purpose to 250.00 USD to show the verifier at work.
- Everything is labelled `"simulated": true` in `dispute_defender/replay/data/replay.json`, and each dispute's sources are shown on its page. Nothing is sent anywhere and nothing is written to disk; restart the app to reset it.

Details and limits: [`dispute_defender/replay/README.md`](dispute_defender/replay/README.md).

<!-- SCREENSHOT: replay-n1-verified -->
<!-- SCREENSHOT: replay-3-blocked-flagged -->
<!-- SCREENSHOT: replay-2-refused -->

## Evaluation results (simulated data)

> **All evaluation data is simulated.** 24 scenarios were written by the author for this evaluation, with hand-written ground truth. One dispute reason (item not received), no real buyers or merchants. Accuracy on real disputes was not measured.

Full report: [`evaluation/results.md`](evaluation/results.md). Scoring definitions: ADR-011 in [`DECISIONS.md`](DECISIONS.md).

**Part A: live Bedrock drafts** (2026-11-11, 144 calls, 24 scenarios × 3 repetitions per model)

| | `us.anthropic.claude-sonnet-4-6` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |
|---|---|---|
| Calls / accepted / rejected / errors | 72 / 72 / 0 / 0 | 72 / 72 / 0 / 0 |
| Model errors (wrong value, claim about a missing fact, duplicate) | 0/390 | 0/390 |
| Incorrect claims VERIFIED / in a send plan | 0 / 0 | 0 / 0 |
| Correct claims wrongly rejected | 0/384 | 0/384 |
| Scenarios with identical output in every repetition | 24 of 24 | 24 of 24 |
| Disagreements between ground truth and verifier | none | none |

How to read it:
- **The effective sample is 24 distinct cases per model, not 72.** Outputs were identical across the 3 repetitions in all 24 scenarios.
- **The 6 incorrect claims per model that would have been sent without the verifier are not model errors.** They are counted from the same outputs, not from a separate experiment. All 6 come from one scenario: R2, where the merchant record belongs to another transaction. That is 3 repetitions × 2 claims (tracking number and carrier). They are *unsupported* claims: the model never sees the record's transaction ID. The verifier FLAGGED all 6 and none reached a send plan.
- Scenarios, scoring, prompt and pipeline were frozen (hashed) at 03:57:46 UTC, before the first live call at 04:08:13 UTC. All 144 calls ran with the frozen hashes, and no change was declared after the results were seen ([`evaluation/DECLARED_CHANGES.md`](evaluation/DECLARED_CHANGES.md)).
- Cost and per-call latency were not recorded.
- Prompt injection: in the three injection scenarios, neither model claimed a manipulated value. This holds only for these simulated scenarios and author-written injections.

**Part B: offline fault injection** (1,192 cases on the same 24 scenarios, no model call). Most cases alter one correct claim and run it through the real verifier and send gate. The `tool_input` cases instead hand a faulty tool call to the real drafter validation. 84 cases are correct values that must not be rejected (82 equivalent values, 2 local dates).

| Fault group | Applied | Caught | Faulted value reached a send plan |
|---|---|---|---|
| amount | 190 | 190 | 0 |
| date | 105 | 105 | 0 |
| seller_protection | 43 | 43 | 0 |
| source_type | 304 | 304 | 0 |
| tool_input | 288 | 288 | 0 |
| tracking_carrier | 68 | 68 | 0 |
| transaction_id | 67 | 67 | 0 |
| **merchant_record (blind spot)** | **43** | **0** | **20** |

- 1,065 of 1,065 altered claims were caught. The faults were written with knowledge of the verifier's rules, so this rate is expected by construction.
- **Known blind spot:** when the merchant record itself is altered, 0 of 43 faults are caught and 20 reach a send plan. The verifier trusts the merchant record.
- Equivalent values (an extra trailing zero, carrier case, spaces): 82 of 82 VERIFIED. A correct local date near midnight: 2 of 2 BLOCKED by design, because dates are compared in UTC.

Zero observed errors does not mean a zero error rate; no confidence intervals are claimed. The full limitations list is in [`evaluation/results.md`](evaluation/results.md#limitations).

## How it works

```
PayPal GET dispute ─► prompt (fact allowlist + buyer message as untrusted text)
                   ─► Claude on Bedrock, forced submit_claims tool        [AI]
                   ─► schema validation of the tool output                [code]
                   ─► verifier: VERIFIED / FLAGGED / BLOCKED per claim    [code]
                   ─► renderer: fixed template, VERIFIED claims only       [code]
                   ─► send gate                                           [code]
                   ─► merchant clicks Approve ─► re-read, re-draft, re-verify, hash check
                   ─► POST provide-evidence (live mode only) ─► GET dispute (read-back)
```

**AI vs. deterministic.** The model only proposes claims (`transaction_id`, `amount`, `transaction_date`, `seller_protection`, `tracking_number`, `carrier`), each with a value and a source, through a forced tool call. It never writes the text that is sent and never sends anything. Everything after the tool call is plain code:
- [`dispute_defender/drafter/`](dispute_defender/drafter/): prompt builder, Bedrock client (Converse API, forced tool, retry on throttling only), output validation.
- [`dispute_defender/claims/verifier.py`](dispute_defender/claims/verifier.py): compares each claim with the PayPal dispute data (transaction ID, amount, UTC date, seller protection) or the merchant record (tracking number, carrier). Other claim types are FLAGGED as unsupported. Rules: ADR-008.
- [`dispute_defender/response/render.py`](dispute_defender/response/render.py): writes the response text from a fixed template, one sentence per VERIFIED claim.
- [`dispute_defender/response/send.py`](dispute_defender/response/send.py): the send gate.

**PayPal endpoints** (sandbox host `api-m.sandbox.paypal.com`; any other host is refused). Client: [`dispute_defender/paypal/client.py`](dispute_defender/paypal/client.py).
- `POST /v1/oauth2/token`
- `GET /v1/customer/disputes` (list page)
- `GET /v1/customer/disputes/{id}` (dispute page, Draft, Approve, read-back, Refresh)
- `POST /v1/customer/disputes/{id}/provide-evidence` (Approve, live mode only): `PROOF_OF_FULFILLMENT` with tracking info and the rendered notes, no files.
- The client also has `send-message`, but the web app does not call it. The sandbox helper script also uses `/v2/checkout/orders` to create test payments.

**Bedrock models** (`us-east-1`, Converse API; IDs come from `BEDROCK_MODEL_ID` / `BEDROCK_MODEL_ID_SECONDARY` and are not hard-coded):
- Primary `us.anthropic.claude-sonnet-4-6`: used by the web app ([`dispute_defender/web/__main__.py`](dispute_defender/web/__main__.py)).
- Secondary `us.anthropic.claude-haiku-4-5-20251001-v1:0`: used in the evaluation comparison and available in the drafter smoke script.
- **Each Draft and each Approve is one Bedrock call (up to 3 attempts, retried on throttling only)**, because Approve drafts and verifies again on the server.

**Safety gates** (ADR-010):
- Only VERIFIED claims are rendered or sent. FLAGGED and BLOCKED claims are shown with their reasons, and the merchant cannot override a verdict.
- The send gate refuses when any of these holds:
  - the freshly read dispute does not offer the `provide_evidence` link;
  - the tracking number and the carrier are not each VERIFIED exactly once;
  - the carrier is not in the fixed list (`FEDEX` only);
  - nothing can be rendered;
  - the notes exceed 2,000 characters;
  - the text's SHA-256 differs from the hash of the text the merchant was shown.
- Approve re-reads the dispute, checks the link before any model call, then drafts, verifies and renders again. Verdicts are never read from the browser.
- Form posts carry a single-use HMAC CSRF token (per-process random key, 15-minute expiry) and must pass an Origin check. The app binds to `127.0.0.1` only, with a Host allowlist (`127.0.0.1`, `localhost`). Templates autoescape. There is no database and nothing is saved to disk.
- **Dry run is the default.** Live sending needs `DISPUTE_DEFENDER_SEND_MODE=live` exactly; any other value means dry. Dry mode does every step except the provide-evidence POST. Every page shows which mode is on.
- If the send times out or PayPal answers 5xx, the page says the outcome is unknown and asks the merchant to check the state before retrying. No automatic retry.

## Run it for real (PayPal sandbox)

No shared credentials are provided. The no-credentials path is [replay mode](#try-it-without-credentials-replay-mode); the real path needs your own PayPal sandbox app and Bedrock access.

Requirements:
- Python 3.14. Verified with 3.14.7; other versions were not tested.
- A PayPal **sandbox** REST app (developer.paypal.com > Apps & Credentials > Sandbox) and a sandbox buyer account to create test payments and disputes.
- AWS access to Amazon Bedrock in `us-east-1` for `us.anthropic.claude-sonnet-4-6` (and `us.anthropic.claude-haiku-4-5-20251001-v1:0` for the comparison), through an AWS CLI profile. AWS keys never go in `.env`.

Setup:

```
git clone https://github.com/jorgedoiany/dispute-defender.git
cd dispute-defender
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-dev.txt
cp .env.example .env
```

Fill in `.env` with your own values. The variable names are in [`.env.example`](.env.example):
- `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_BASE_URL` (sandbox only)
- `AWS_REGION`, `BEDROCK_MODEL_ID`, `BEDROCK_MODEL_ID_SECONDARY`, `AWS_PROFILE`
- `DISPUTE_DEFENDER_SEND_MODE`

Never commit `.env`; it is in `.gitignore`.

Run:

```
# Dry run (default): every step except the provide-evidence POST
.venv/bin/python -m dispute_defender.web

# Live sandbox send: Approve sends provide-evidence to the PayPal sandbox
DISPUTE_DEFENDER_SEND_MODE=live .venv/bin/python -m dispute_defender.web
```

Open `http://127.0.0.1:8000` (change it with `--port N`). The app reads `.env` without overriding variables already set in the shell. In live mode every page shows a LIVE SANDBOX SEND banner.

Make a sandbox dispute that can be answered. Run one step at a time and check the output before the next:
1. `.venv/bin/python scripts/spike_sandbox.py create-order`, then open the printed link and approve the payment as the sandbox buyer.
2. `.venv/bin/python scripts/spike_sandbox.py capture --order-id <ORDER_ID>`
3. As the sandbox buyer, open the sandbox Resolution Center and report "item not received" for that payment.
4. Run `.venv/bin/python scripts/spike_sandbox.py list` until the dispute appears. Then run `show --dispute-id <DISPUTE_ID>` until it reads `WAITING_FOR_SELLER_RESPONSE` with the `provide-evidence` link. A new dispute may read `UNDER_REVIEW` for a few minutes first.

On the dispute page, enter the tracking number and carrier from your order record. The carrier list holds `FEDEX` only.

Tests (offline; no credentials or network): `.venv/bin/python -m pytest`. Offline UI preview: `.venv/bin/python scripts/preview_ui.py`. Other smoke and evaluation scripts are listed in [`AGENTS.md`](AGENTS.md#commands).

<!-- SCREENSHOT: live-send-readback -->

## Sandbox notes and limitations

- **Sandbox only.** The app was not tested in production or with real money, and the code refuses any PayPal host other than the sandbox.
- **`adjudicate` was refused 3 times.** The sandbox call that should settle a dispute returned `ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE` every time, and its link never appeared. So the app shows that PayPal *accepted* the evidence, not that a dispute was *won*.
- **`require-evidence` was never offered**, so it was never called.
- **Evidence content is not read back.** The dispute's `evidences[]` entries have no field holding the submitted tracking info. The read-back confirms the new state, not what PayPal stored.
- **`allowed_response_options` listed only `accept_claim`** while the `provide_evidence` link was offered and evidence was then accepted. The send gate therefore relies on the `provide_evidence` link only.
- **`UNDER_REVIEW` is short-lived.** After evidence, the dispute read `UNDER_REVIEW` with only the `self` link, then `WAITING_FOR_BUYER_RESPONSE` a few minutes later without any call from the app.
- **The verifier trusts the merchant record.** A wrong tracking number in the merchant's own record is not caught (Part B blind spot above).
- One dispute reason (item not received) and one carrier (`FEDEX`). PayPal's limit on `notes` length was not verified; the app's 2,000-character cap is an assumption.
- Dates are compared in UTC, so a correct local date near midnight is BLOCKED.
- FLAGGED and BLOCKED claims in the app, and the unknown-outcome page, were tested offline only. The app was checked only in Chrome; concurrent requests were not tested.
- An access token revoked early is not retried (backlog T-011).

Run logs for every sandbox step: [`PROGRESS.md`](PROGRESS.md). Decisions: [`DECISIONS.md`](DECISIONS.md).

## Feedback on the PayPal Disputes API

Only things observed in our sandbox runs (details in [`PROGRESS.md`](PROGRESS.md)):

1. **The sandbox `adjudicate` call could not be used to finish a test dispute.** It was refused in every state tried: `WAITING_FOR_BUYER_RESPONSE`/`INQUIRY`, `UNDER_REVIEW`/`INQUIRY` and `UNDER_REVIEW`/`CHARGEBACK`. Its link never appeared. Seen on dispute `PP-R-HBV-10197617`, T-002 steps 8, 11 and 14.
2. **The error name is generic.** These refusals came back as HTTP 400 named `INVALID_REQUEST`; only the issue code `ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE` said what was wrong. Same dispute and steps.
3. **`send-message` accepted a JSON body although the API spec lists only multipart.** Seen on `PP-R-HBV-10197617` (T-002 step 9) and `PP-R-KXL-10197854` (T-003 step 8).
4. **The submitted evidence cannot be read back.** `evidences[0]` holds only `date`, `dispute_life_cycle_stage`, `evidence_type`, `notes` and `source`, with no tracking info, so a client cannot confirm what was stored. Seen on `PP-R-KXL-10197854` and `PP-R-HBV-10197617` (T-004, `show --nested-keys`).
5. **`allowed_response_options` did not match the offered links.** It held only `accept_claim` while the `provide_evidence` link was offered, and provide-evidence was then accepted. Seen on `PP-R-UXH-10198605` (T-006 live send).
6. **Status changes without a call, and quickly.** After provide-evidence, `UNDER_REVIEW` changed to `WAITING_FOR_BUYER_RESPONSE` within minutes. Seen on `PP-R-HBV-10197617` (T-002 steps 7 to 8), `PP-R-KXL-10197854` (T-003 steps 6 to 7) and `PP-R-UXH-10198605` (T-006 state timeline). A client must re-read state before acting.

## Repository structure

```
dispute_defender/
  paypal/      REST client, config (sandbox host guard), pydantic models, typed errors
  drafter/     prompt, Bedrock client, output schema and validation
  claims/      claim models and the deterministic verifier
  response/    renderer, send gate, carrier list
  web/         FastAPI approval app, CSRF, templates
  evaluation/  scenario loader, scoring, fault injection, runner, report
  replay/      replay clients and simulated replay data
scripts/       sandbox spike, smoke checks, UI preview, evaluation CLI
evaluation/    simulated scenarios, freeze hashes, raw results, results.md
tests/         offline pytest suite and hand-written fixtures
AGENTS.md  TASKS.md  PROGRESS.md  DECISIONS.md
```

Demo video: TODO (T-009).

## License

MIT. See [`LICENSE`](LICENSE).
