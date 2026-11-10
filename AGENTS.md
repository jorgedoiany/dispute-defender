# AGENTS.md

## Project
- App: Dispute Defender (working name)
- Purpose and users: helps a PayPal merchant answer a dispute. An AI model drafts the response as structured claims, deterministic code verifies each claim against PayPal API data, and the merchant approves before anything is sent.
- Stack (confirmed 2026-11-09, see DECISIONS.md): Python with a direct REST client for PayPal, a pipeline with structured model output, Claude on Amazon Bedrock, FastAPI with a simple HTML approval page.
- Environment: PayPal **sandbox only**. Never real money or real accounts.

## Start here
Read TASKS.md and PROGRESS.md. Consult DECISIONS.md for accepted choices. Project principles are in the Working rules below.

## Commands
Verified on 2026-11-09 with Python 3.14 during T-002, unless marked TODO.
- Install: `python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt` (dependencies are provisional until T-003)
- Run locally: TODO: verify
- Test: TODO: verify
- Lint/typecheck/build: TODO: decide whether any are used, then verify
- Sandbox spike: `.venv/bin/python scripts/spike_sandbox.py <step> [options]`. Reads `.env`; refuses any host other than `api-m.sandbox.paypal.com`. One step per run:
  - `token`, `create-order`, `capture --order-id ID`, `list`, `show --dispute-id ID`
  - `provide-evidence`, `send-message`, `escalate`, `adjudicate --outcome SELLER_FAVOR|BUYER_FAVOR` (each with `--dispute-id ID`)
  - Not yet run: `require-evidence` and `send-message --format multipart`. `adjudicate` runs but PayPal refused it in T-002 (see PROGRESS.md).

## Structure
Only paths confirmed in the brief are listed. Add others when they exist.
- `scripts/spike_sandbox.py`: sandbox spike that decided the idea is viable (T-002, ADR-007)
- `requirements.txt`: provisional dependencies until T-003
- TODO: layout for the REST client, claim schema, verifier, drafter and web app (decide in T-003)

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
