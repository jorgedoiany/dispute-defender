# TASKS.md

## MVP goal
A merchant opens a PayPal sandbox dispute, reviews a drafted response whose every claim was checked against PayPal API data, approves it, and sees the response sent in the sandbox and the dispute's new state confirmed.

Target dates: core build Nov 9-10; README, license, video and submission Nov 11 (deadline Nov 12, 12:00 PT).

## Current task
None started. Next: T-001.

## Backlog

### T-001: Create the public repository
- Priority: P0
- Status: Todo
- Depends on: none
- Acceptance criteria:
  - [ ] A public GitHub repository exists with an open-source license visible in the About section (license choice recorded in DECISIONS.md)
  - [ ] `.env` is listed in `.gitignore` and `.env.example` has no real values
  - [ ] AGENTS.md, TASKS.md, PROGRESS.md, DECISIONS.md and CLAUDE.md are committed at the repo root

### T-002: Sandbox spike (gate for the idea)
- Priority: P0
- Status: Todo
- Depends on: T-001
- Acceptance criteria:
  - [ ] `scripts/spike_sandbox.py` runs against the PayPal sandbox with the author's credentials
  - [ ] It creates and captures an order with the sandbox buyer
  - [ ] The buyer opens an "item not received" case (manually in the sandbox Resolution Center if the API cannot create it)
  - [ ] It lists and shows the dispute, calls require-evidence, sends a message, provides evidence, and adjudicates
  - [ ] The HTTP status and a short result for each step are written in PROGRESS.md
  - [ ] A go / fallback decision is recorded in DECISIONS.md (fallback: authorize / capture / void flow)

### T-003: PayPal REST client
- Priority: P0
- Status: Todo
- Depends on: T-002
- Acceptance criteria:
  - [ ] Gets an OAuth token and calls list/show dispute, send-message and provide-evidence against the sandbox
  - [ ] Responses are validated at the boundary; errors are raised explicitly
  - [ ] Credentials come from environment variables only

### T-004: Claim schema and deterministic verifier
- Priority: P0
- Status: Todo
- Depends on: T-003
- Acceptance criteria:
  - [ ] A claim has a value and a claimed source (amount, dates, tracking, etc.)
  - [ ] The verifier compares each claim to PayPal API data and marks it verified, flagged or blocked
  - [ ] Tests cover a matching claim and a mismatching claim (test command recorded in AGENTS.md once verified)

### T-005: Model drafter on Bedrock
- Priority: P0
- Status: Todo
- Depends on: T-004
- Acceptance criteria:
  - [ ] Given a dispute and its transaction data, Claude on Bedrock returns structured claims as JSON that the schema accepts
  - [ ] Invalid model output is rejected, not sent on
  - [ ] Model ID and AWS setup are recorded in AGENTS.md

### T-006: Approval page and send
- Priority: P0
- Status: Todo
- Depends on: T-005
- Acceptance criteria:
  - [ ] A FastAPI page shows the dispute, each claim with its verification result, and Approve / Reject
  - [ ] Blocked claims cannot be sent
  - [ ] Approving sends the response in the sandbox and the page shows the dispute's new state read back from PayPal

### T-007: Small evaluation
- Priority: P1
- Status: Todo
- Depends on: T-006
- Acceptance criteria:
  - [ ] About 20-30 disputes with seeded errors (wrong amount, date or tracking); simulated cases are labelled as simulated
  - [ ] Metric: wrong claims that reach the send step, model-only draft vs. draft with verifier
  - [ ] Result and its limits are written down

### T-008: README, license check and secrets scan
- Priority: P0
- Status: Todo
- Depends on: T-006 (T-007 for the results section)
- Acceptance criteria:
  - [ ] README starts with what it does and the measured result, then setup and run steps, which PayPal sandbox and AI model are called, and known limitations
  - [ ] A fresh clone can follow the README to run the main path with sandbox credentials
  - [ ] Secrets scan run on the repo and history; result recorded in PROGRESS.md
  - [ ] License is visible in the About section

### T-009: Demo video and submission
- Priority: P0
- Status: Todo
- Depends on: T-008
- Acceptance criteria:
  - [ ] Video under 3 minutes, public on YouTube, in English, showing the main path running
  - [ ] Submission fields completed against the official requirements checklist

### T-010: Replay mode for judges without credentials
- Priority: P2
- Status: Todo
- Depends on: T-006
- Acceptance criteria:
  - [ ] Recorded sandbox responses can drive the flow, clearly labelled as replay and not the default

## Later
- Appeals and escalation flows
- Multiple merchants or accounts
- Anything beyond the single dispute type used in the spike

## Done
No verified completed work yet.
