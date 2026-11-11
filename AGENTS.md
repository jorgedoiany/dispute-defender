# AGENTS.md

## Project
- App: Dispute Defender (working name)
- Purpose and users: helps a PayPal merchant answer a dispute. An AI model drafts the response as structured claims, deterministic code verifies each claim against PayPal API data, and the merchant approves before anything is sent.
- Stack (confirmed 2026-11-09, see DECISIONS.md): Python with a direct REST client for PayPal, a pipeline with structured model output, Claude on Amazon Bedrock, FastAPI with a simple HTML approval page.
- Model (ADR-003): Claude on Amazon Bedrock in `us-east-1`. Primary `us.anthropic.claude-sonnet-4-6`; secondary `us.anthropic.claude-haiku-4-5-20251001-v1:0` for T-007. IDs are read from `BEDROCK_MODEL_ID` / `BEDROCK_MODEL_ID_SECONDARY`, never hard-coded. AWS credentials come from the AWS CLI profile (boto3 credential chain), never from the repo.
- Environment: PayPal **sandbox only**. Never real money or real accounts.

## Start here
Read TASKS.md and PROGRESS.md. Consult DECISIONS.md for accepted choices. Project principles are in the Working rules below.

## Commands
Verified on 2026-11-09 with Python 3.14 (install and test commands re-verified with 3.14.7 in T-003), unless marked TODO.
- Install: `python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-dev.txt` (runtime only: `requirements.txt`)
- Run locally (dry run, the default): `.venv/bin/python -m dispute_defender.web [--port N]`, then open `http://127.0.0.1:8000`. Binds to 127.0.0.1 only (no host option). Reads `.env` without overriding variables already set in the shell, and the AWS CLI profile. Each Draft and each Approve is **one billed Bedrock call**. Dry run does every step except the provide-evidence POST. Verified in Chrome on 2026-11-10 (T-006).
- Run locally, live sandbox send: `DISPUTE_DEFENDER_SEND_MODE=live .venv/bin/python -m dispute_defender.web`. Approve then sends provide-evidence to the PayPal sandbox; every page shows the LIVE SANDBOX SEND banner. Any value other than `live` means dry. Verified with one live send on 2026-11-10 (T-006).
- Run locally, replay (T-010, ADR-012; no credentials, no network): `.venv/bin/python -m dispute_defender.web --replay [--port N]`. Only the flag turns it on; it reads no `.env`, builds no PayPal or Bedrock client and ignores `DISPUTE_DEFENDER_SEND_MODE`. Three disputes from `dispute_defender/replay/data/replay.json` (hand-written, **simulated**; model outputs rebuilt from claims recorded on simulated scenarios in T-007); Approve records the evidence in memory only; restart to reset. Every page shows the REPLAY banner. What to type per dispute: `dispute_defender/replay/README.md`. Verified with offline tests and a local uvicorn run driven by curl on 2026-11-11; the author's browser check is pending.
- Make a sandbox dispute that can be answered (manual buyer steps; one step per run, check the output before the next):
  1. `.venv/bin/python scripts/spike_sandbox.py create-order`, then open the printed link and approve as the sandbox buyer.
  2. `.venv/bin/python scripts/spike_sandbox.py capture --order-id ID`
  3. As the sandbox buyer, in the sandbox Resolution Center, report "item not received" for that payment.
  4. `.venv/bin/python scripts/spike_sandbox.py list` until the dispute appears, then `show --dispute-id ID` until it is `WAITING_FOR_SELLER_RESPONSE` with the `provide-evidence` link (in T-006 it was first `UNDER_REVIEW`, then changed a few minutes later).
- UI preview (offline): `.venv/bin/python scripts/preview_ui.py [--out DIR]`. Renders every page (list, dispute, dispute refused, draft and result in dry and live mode, state, refusal and error pages) through the real app with test fixtures, a fake model and a fake CSRF token, and writes static HTML to `ui-preview/` (gitignored); open `ui-preview/index.html`. No PayPal, no Bedrock, no network, no `.env`. Needs `requirements-dev.txt`. Verified on 2026-11-10 (T-012).
- Test: `.venv/bin/python -m pytest` (offline; no credentials or network needed; AWS env, profile files and botocore's HTTP send are blocked in `tests/conftest.py`). Re-verified in T-006 on 2026-11-10, including the renderer, send gate, web app and CSRF tests.
- Client smoke check: `.venv/bin/python scripts/smoke_client.py <step> [--dispute-id ID]`. Steps: `token`, `list`, `show`, `provide-evidence`, `send-message`. Reads `.env`; sandbox only. All five steps verified against the sandbox in T-003 (see PROGRESS.md). `show --nested-keys` also prints key names (no values) one level down in `disputed_transactions[0]`, `evidences[0]`, `messages[0]` and `offer`; verified in T-004.
- Verifier smoke check: `.venv/bin/python scripts/smoke_verifier.py --dispute-id PP-R-KXL-10197854|PP-R-HBV-10197617`. Read only (GET); runs fixed test claims through `verify_claims` and prints verdicts and reasons only. Reads `.env`; sandbox only. Verified on both disputes in T-004.
- Drafter smoke check: `.venv/bin/python scripts/smoke_drafter.py --dispute-id ID [--model primary|secondary] [--no-record]`. One PayPal sandbox GET, **one billed Bedrock Converse call**, then the verifier; nothing is sent to PayPal or the buyer. Reads `.env` and the AWS CLI profile. Prints verdicts, model ID, token counts and claim values cut to 60 characters; never the prompt, buyer message text or credentials. Exit 0 ok, 1 error, 2 draft rejected. Verified live on 2026-11-10 (primary on both sandbox disputes, secondary on one).
- Evaluation (T-007, **simulated scenarios**, ADR-011): `.venv/bin/python scripts/run_evaluation.py <step>`. Never calls PayPal.
  - `faults`: Part B, offline fault injection, writes `evaluation/results/faults.json`. Free. Verified on 2026-11-10.
  - `freeze`: records the hashes of scenarios, scoring, prompt and pipeline in `evaluation/frozen.json`. Commit it before a live run.
  - `run --dry-run [--model primary|secondary|both] [--repetitions N] [--scenarios IDS]`: prints calls, estimated tokens, models, time and freeze status; no client, no call. Dollars only with `--price-in-per-m` and `--price-out-per-m` (author-supplied, one model at a time). Verified on 2026-11-10.
  - `run --confirm-spend --out evaluation/results/raw-<date>.jsonl`: Part A, **billed Bedrock calls** (144 for both models, 3 repetitions). Refused without a matching freeze; hard cap `--max-calls` (default 144, ceiling 200, earlier attempts in the file count); aborts on config errors, throttling or 3 errors in a row; rerun the same command to resume. Exit 0 ok, 1 config, 3 no `--confirm-spend`, 4 aborted, 5 refused. Run live by the author on 2026-11-11 (144 calls, 0 errors).
  - `report`: writes `evaluation/results.md` from the raw results, `faults.json`, the freeze and `evaluation/DECLARED_CHANGES.md`. Verified offline on 2026-11-10.
- Lint/typecheck/build: TODO: decide whether any are used, then verify
- Sandbox spike: `.venv/bin/python scripts/spike_sandbox.py <step> [options]`. Reads `.env`; refuses any host other than `api-m.sandbox.paypal.com`. One step per run:
  - `token`, `create-order`, `capture --order-id ID`, `list`, `show --dispute-id ID`
  - `provide-evidence`, `send-message`, `escalate`, `adjudicate --outcome SELLER_FAVOR|BUYER_FAVOR` (each with `--dispute-id ID`)
  - Not yet run: `require-evidence` and `send-message --format multipart`. `adjudicate` runs but PayPal refused it in T-002 (see PROGRESS.md).

## Structure
Only paths confirmed in the brief are listed. Add others when they exist.
- `scripts/spike_sandbox.py`: sandbox spike that decided the idea is viable (T-002, ADR-007)
- `scripts/smoke_client.py`: live sandbox check of the app's PayPal client, one step per run (T-003)
- `scripts/smoke_verifier.py`: live read-only check of the claim verifier on the two sandbox disputes (T-004)
- `scripts/smoke_drafter.py`: live check of the drafter: PayPal GET, one Bedrock call, verifier (T-005)
- `scripts/preview_ui.py`: offline static preview of every page of the approval app (T-012)
- `scripts/run_evaluation.py`: T-007 evaluation on simulated scenarios: `faults`, `freeze`, `run`, `report`
- `dispute_defender/`: the app package
  - `paypal/config.py`: `PayPalConfig`, `load_config()` from environment variables, sandbox host guard
  - `paypal/errors.py`: `PayPalError` and subclasses; messages carry only HTTP status, name, issue codes and debug_id
  - `paypal/models.py`: pydantic models for the fields the app uses (dispute id, status, stage, reason, amount, links, seller-side fields of `disputed_transactions`, `messages` kept out of dump and repr) and the evidence input
  - `paypal/client.py`: `PayPalClient` (`get_token`, `list_disputes`, `get_dispute`, `send_message`, `provide_evidence`)
  - `claims/models.py`: `Claim`, `MerchantOrderRecord`, `Verdict`, `ClaimResult` (ADR-008)
  - `claims/verifier.py`: deterministic `verify_claim()` / `verify_claims()`; the rules per claim type are in the module docstring
  - `drafter/` (ADR-009):
    - `schema.py`: `DraftOutput` and the `submit_claims` tool spec; keep it matched to `claims/verifier.py`
    - `prompt.py`: `build_prompt()`, the fact allowlist and the untrusted buyer-message block
    - `client.py`: `ModelClient` interface, `ModelRequest`, `ModelResponse`
    - `bedrock.py`: `BedrockModelClient` (Converse, forced tool, retry on throttling only)
    - `drafter.py`: `draft_claims()` and output validation (`DraftRejected`)
    - `config.py`, `errors.py`: env config and typed errors with safe messages
  - `response/` (ADR-010):
    - `render.py`: `render_notes()`, the fixed template that writes the response text from VERIFIED claims only
    - `send.py`: `prepare_send()` send gate (`SendPlan` or `Refusal`), `check_dispute_sendable()`, `notes_hash()`
    - `carriers.py`: the fixed carrier list (`FEDEX` only) and `canonical_carrier()`
  - `web/` (ADR-004, ADR-010):
    - `app.py`: `create_app()`, the FastAPI routes, error pages and security headers
    - `csrf.py`: single-use HMAC CSRF tokens bound to dispute and purpose
    - `forms.py`: tracking and carrier input to `MerchantOrderRecord`
    - `views.py`: cleaned, cut display values for the templates
    - `settings.py`: send mode (`DISPUTE_DEFENDER_SEND_MODE`), host and port
    - `__main__.py`: `python -m dispute_defender.web`, uvicorn on 127.0.0.1
    - `templates/`: Jinja2 templates (autoescape on)
  - `evaluation/` (T-007, ADR-011): `scenarios.py` (loader, refuses unlabelled files), `pipeline.py` (verifier and send gate on given claims), `scoring.py` (ground-truth classes and metrics), `faults.py` (Part B), `fake.py` (scripted model clients, offline only), `runner.py` (Part A with cap, abort and resume), `freeze.py` (hashes), `report.py` (`results.md`)
  - `replay/` (T-010, ADR-012): `data.py` (loader, refuses unlabelled data), `paypal.py` (`ReplayPayPalClient`), `model.py` (`ReplayModelClient`), `data/replay.json` (simulated replay data), `README.md` (sources, what to type, limits)
- `evaluation/`: **simulated** evaluation data and results: `scenarios/*.json` (24), `README.md`, `frozen.json`, `DECLARED_CHANGES.md`, `results/` (raw JSONL and `faults.json`), `results.md` (generated)
- `tests/`: offline pytest suite; `tests/fixtures/paypal/` and `tests/fixtures/bedrock/` hold hand-written payloads
- `requirements.txt` (runtime) and `requirements-dev.txt` (tests), pinned

## Working rules
- Keep changes within the current task and follow existing patterns.
- The model drafts; it never sends. Every claim in a draft must be checked by code against PayPal API data before the approval step.
- A response is sent only after explicit merchant approval in the web page.
- Validate all external input (PayPal responses, model output) at the boundary. Handle errors explicitly.
- Keep secrets out of source control, logs and UI messages. Use `.env`; `.env` must be in `.gitignore`.
- Any replay mode (recorded sandbox responses) must be clearly labelled and never the default path.
- Evaluation data that is simulated must be labelled as simulated.
- Record material architecture changes in DECISIONS.md.
- All repo text is in English.
- This repository is public. Do not add private notes or personal data.

## Git workflow
- `main` is always in a working state. Do not commit directly to `main` after the initial setup commit (T-001).
- One branch per task, named `<type>/<task-id>-<short-name>`, for example `feat/t-003-paypal-client`. Types: `feat`, `fix`, `docs`, `chore`.
- Commits use conventional commits (`feat:`, `fix:`, `docs:`, `chore:`), in English, small and focused.
- Open a pull request to `main` for each task and fill in `.github/pull_request_template.md`. Merge with squash.
- Before opening a PR: run the relevant checks and report actual results, confirm no secrets are staged, and update TASKS.md and PROGRESS.md.
- Never force-push to `main`.

## Scope boundaries
In scope: the flow in TASKS.md. Out of scope until the MVP works: see "Later" in TASKS.md.

## Completion
Run the relevant checks and report actual results, or say why a check was not run.
Update task status in TASKS.md and the handoff in PROGRESS.md to match observed work.
Do not claim a requirement is met unless the code actually does it.
