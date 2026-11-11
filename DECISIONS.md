# DECISIONS.md

## Index
- ADR-001: Python with a direct REST client for PayPal (Accepted)
- ADR-002: Pipeline with structured output, not a free-roaming agent (Accepted)
- ADR-003: Claude on Amazon Bedrock as the model (Accepted)
- ADR-004: FastAPI with a simple HTML approval page (Accepted)
- ADR-005: Fallback flow if the sandbox spike fails (Superseded by ADR-007)
- ADR-006: Open-source license (Accepted: MIT)
- ADR-007: Go with Dispute Defender after the sandbox spike (Accepted)
- ADR-008: Claim schema and deterministic verdict rules (Accepted)
- ADR-009: Bedrock drafter returns claims only, through a forced tool (Accepted)
- ADR-010: Send path: VERIFIED-only rendering, re-verify on approve, local dry-by-default app (Accepted)
- ADR-011: Evaluation scoring definitions for T-007 (Accepted)
- ADR-012: Replay mode for judges: two clients swapped, CLI flag only (Accepted)

## Entry template
### ADR-[number]: [title]
- Date: [date]
- Status: Proposed / Accepted / Superseded
- Supersedes: [previous ADR, if any]

#### Context
[problem and constraints]
#### Decision
[chosen approach, or proposed approach awaiting a decision]
#### Alternatives
[options and tradeoffs]
#### Consequences
[benefits, costs, limitations]

To change a decision, do not edit or delete the old entry. Change its status to Superseded, add a new entry with `Supersedes: ADR-[old number]`, and explain the reason for the change in the new entry's Context.

## Entries

### ADR-001: Python with a direct REST client for PayPal
- Date: 2026-11-09
- Status: Accepted
- Supersedes: none

#### Context
The flow needs the PayPal Disputes API. The PayPal Agent Toolkit documents invoice and order tools, not disputes.
#### Decision
Use Python and call the PayPal REST API directly.
#### Alternatives
Agent Toolkit or MCP server: not chosen because disputes are not documented there.
#### Consequences
More code to write for OAuth and endpoints, but full control over the Disputes calls.

### ADR-002: Pipeline with structured output, not a free-roaming agent
- Date: 2026-11-09
- Status: Accepted
- Supersedes: none

#### Context
Wrong claims in a dispute response are costly, and the check must not depend on the model.
#### Decision
The model drafts claims as JSON; deterministic code verifies each claim against PayPal API data before the merchant approves.
#### Alternatives
A free-roaming agent that decides and acts: harder to verify and to demo.
#### Consequences
Less autonomy; a clear place to measure errors that reach the send step.

### ADR-003: Claude on Amazon Bedrock as the model
- Date: 2026-11-09
- Status: Accepted
- Supersedes: none

#### Context
The project must call an AI model in code. The model ID and credentials setup were left open on 2026-11-09 and completed on 2026-11-10 for T-005, after a minimal Converse call from the author's AWS account.
#### Decision
Use Claude on Amazon Bedrock.
- Region: `us-east-1`.
- Primary model: `us.anthropic.claude-sonnet-4-6` (responded OK on 2026-11-10).
- Secondary model, for the T-007 comparison: `us.anthropic.claude-haiku-4-5-20251001-v1:0` (responded OK on 2026-11-10).
- Auth: the AWS CLI default profile through the standard boto3 credential chain. No AWS keys in the repo, ever.
- Rationale: the safety comes from the deterministic verifier (ADR-002, ADR-008), not from the model, so a capable but cheaper model is enough.
#### Alternatives
- Other model providers: not chosen.
- Not available in this account on 2026-11-10: `us.anthropic.claude-sonnet-5`, `us.anthropic.claude-sonnet-5-5` and `us.anthropic.claude-haiku-5-5` (each returned `AccessDeniedException`); `us.anthropic.claude-sonnet-4-5-20250929-v1:0` (marked Legacy).
#### Consequences
- Judges without AWS access cannot run the model path; see the replay mode task (T-010).
- Model IDs are config, not code: they come from `BEDROCK_MODEL_ID` and `BEDROCK_MODEL_ID_SECONDARY` (see `.env.example`), so a model can change without a code change.
- Availability was checked from one account on one day; another account may see a different list.

### ADR-004: FastAPI with a simple HTML approval page
- Date: 2026-11-09
- Status: Accepted
- Supersedes: none

#### Context
The merchant must approve before anything is sent, and judges need a runnable demo. The main path uses the real sandbox; any replay mode is an extra, labelled, never the default.
#### Decision
Use FastAPI with one simple HTML page.
#### Alternatives
A separate front-end framework: more setup for little gain.
#### Consequences
Minimal interface; the design criterion depends on a clear, complete flow rather than visual polish.

### ADR-005: Fallback flow if the sandbox spike fails
- Date: 2026-11-09
- Status: Superseded (by ADR-007)
- Supersedes: none

#### Context
Disputes in the sandbox may not be creatable or completable as planned. The spike (T-002) decides.
#### Decision
If the spike fails, switch to a hold-before-pay flow (authorize / capture / void). Not accepted until the spike result is known.
#### Alternatives
Keep the disputes idea with simulated data only: weaker against the requirement for a real sandbox flow.
#### Consequences
The AI role in the fallback is weaker.

### ADR-006: Open-source license
- Date: 2026-11-09
- Status: Accepted
- Supersedes: none

#### Context
The official rules require a public repo with an open-source license visible in the About section.
#### Decision
MIT License, in `LICENSE` at the repo root.
#### Alternatives
Any OSI-approved license.
#### Consequences
The choice must be visible in the repository's About section.

### ADR-007: Go with Dispute Defender after the sandbox spike
- Date: 2026-11-09
- Status: Accepted
- Supersedes: ADR-005

#### Context
ADR-005 proposed an authorize / capture / void fallback if the disputes flow could not run in the sandbox. The T-002 spike (results in PROGRESS.md) ran the flow on sandbox dispute `PP-R-HBV-10197617`, an "item not received" case opened manually by the sandbox buyer. Order create and capture, dispute list and show, provide-evidence (at both the INQUIRY and CHARGEBACK stages), send-message and escalate were all accepted, and each new state was read back from PayPal. The sandbox-only `adjudicate` call was refused three times with `ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE`, and PayPal never offered the `adjudicate` or `require-evidence` link.
#### Decision
Go: continue with Dispute Defender on the PayPal Disputes API. The demo ends with the merchant's response accepted and the dispute read back as UNDER_REVIEW, not with a settled dispute.
#### Alternatives
- Fallback flow from ADR-005 (authorize / capture / void): not needed, because the response path works in the sandbox.
- Keep trying to settle disputes through `adjudicate`: not chosen, because it was refused three times in two different stages and the link was never offered.
#### Consequences
- The MVP shows a response sent and the dispute's new state confirmed by PayPal, but not a final outcome.
- Dispute statuses change on their own and UNDER_REVIEW can be short-lived, so the app must read the state back from PayPal rather than assume it.
- Each sandbox dispute needs manual buyer steps in the browser, so evaluation data (T-007) is simulated and labelled as simulated.
- "Accepted by PayPal" means the submission was accepted, not that the evidence would win a real case.

### ADR-008: Claim schema and deterministic verdict rules
- Date: 2026-11-10
- Status: Accepted
- Supersedes: none

#### Context
ADR-002 requires every claim in a draft to be checked by code before the merchant approves. T-004 needs a claim shape the model can produce (T-005) and rules that give the same verdict every time. The nested key names of `disputed_transactions[0]` were observed on two sandbox disputes in T-004 before the model was written; their value formats were confirmed afterwards (see Consequences).
#### Decision
- A claim has a `type`, a `value` and a claimed `source` (`paypal` or `merchant_record`).
- Verdicts: `VERIFIED` (matches the source), `FLAGGED` (no data to check, no or wrong source, unsupported type, or a merchant record that is for a different transaction), `BLOCKED` (contradicts the source data, or the value is invalid).
- The verifier makes no model or network calls. It uses Decimal for amounts and exact matching, except that carrier is compared trimmed and case-insensitively.
- PayPal-backed types: `transaction_id`, `amount` (value and currency against `gross_amount`), `transaction_date` (the UTC calendar date of `create_time`) and `seller_protection` (against `seller_protection_eligible`). They require exactly one disputed transaction; otherwise they are FLAGGED.
- Merchant-record types: `tracking_number` (exact) and `carrier`, checked against a `MerchantOrderRecord` passed in by the caller. Their reasons say "verified against merchant record", never that PayPal verified them. If the record's optional `transaction_id` differs from the dispute's `seller_transaction_id`, they are FLAGGED, never BLOCKED.
- The dispute model takes only the seller-side transaction fields the verifier needs (plus `transaction_status`, with no rule yet). Buyer fields stay out.
#### Alternatives
- Ask the model whether a claim is true: not chosen; the check must not depend on the model (ADR-002).
- Strict enums for type and source in the schema: not chosen, because an unknown type would then fail the whole draft instead of flagging one claim.
- Compare dates in the merchant's time zone: not chosen for the MVP; no time zone is known. Near midnight a local date can be BLOCKED.
#### Consequences
- FLAGGED claims still need the merchant's judgment; T-006 decides how they are shown. BLOCKED claims cannot be sent (T-006).
- Fewer claim types are supported than a full response would need; others are FLAGGED.
- The live value formats of the transaction fields were confirmed on two sandbox disputes, one sample each (`PP-R-KXL-10197854` and `PP-R-HBV-10197617`, T-004): both passed the model, so `create_time` had a timezone, `gross_amount` parsed as money and `seller_protection_eligible` was a JSON boolean. Two samples do not prove PayPal's schema; a different format on another dispute would fail the dispute read at the boundary.
- The verifier checks structured claims only. Any free text in the final response must be rendered from verified claims or treated as unverified; which of the two is decided in T-005/T-006.

### ADR-009: Bedrock drafter returns claims only, through a forced tool
- Date: 2026-11-10
- Status: Accepted
- Supersedes: none

#### Context
ADR-002 says the model drafts structured claims and code checks them; ADR-003 chose Claude on Amazon Bedrock; ADR-008 defined the claims and the verifier and left open how free text in the final response is handled. The dispute's `messages[].content` is free text, mostly written by the buyer, and may contain instructions aimed at the model (prompt injection).
#### Decision
- **Structured output.** The drafter uses the Bedrock Converse API (boto3) with one tool, `submit_claims`, forced through `toolChoice`. The tool's input schema is generated from a pydantic model (`DraftOutput`) with every `$ref` inlined. No extended thinking and no temperature are sent.
- **Validation.** The output is accepted only if the model stopped with `tool_use` and called `submit_claims` exactly once with input that passes `DraftOutput`. Otherwise the whole output is rejected (`DraftRejected`) and nothing from it is passed on.
- **Schema.** Claim types are limited to the ADR-008 types, each with one allowed source (`tracking_number` and `carrier` only from `merchant_record`); no extra fields; strict JSON types; 1 to 20 claims. Value formats (decimal strings, `YYYY-MM-DD` dates, currency codes) are left to the verifier, which BLOCKS a bad value, so the format rules live in one place. A drift test keeps the drafter's types and sources equal to the verifier's rules.
- **Claims only.** The model writes no text for the buyer or PayPal. The text sent to PayPal is rendered by a template from VERIFIED claims only; the renderer is built in T-006. This resolves ADR-008's open consequence on free text: it is rendered from verified claims, never written by the model.
- **Prompt allowlist.** Only these facts reach the model: the dispute's reason, status, stage and amount; from a single disputed transaction, `seller_transaction_id`, the UTC transaction date (computed by code), `gross_amount` and `seller_protection_eligible`; from the merchant record, `tracking_number` and `carrier`. Buyer details (name, email, buyer transaction ID, items) never do.
- **Buyer messages are untrusted data.** They go in a separate delimited block: the last 5 non-empty messages, at most 1,000 characters each and 4,000 in total, with control and bidi characters removed and `<` / `>` escaped so the text cannot close the block. The system prompt says never to follow instructions there or copy values from it. `Dispute.messages` and its content are excluded from `model_dump` and `repr`.
- **Client.** A small `ModelClient` interface, with `BedrockModelClient` as the real implementation and a fake in tests. Timeouts are 5 s connect and 60 s read with botocore retries off; only `ThrottlingException` is retried, at most 3 attempts (1 s, then 2 s). Errors are typed and their messages hold only an error code, HTTP status, request ID or class name, never the prompt, model output values, AWS's message text or credentials.
- Region and model IDs come from the environment (ADR-003).
#### Alternatives
- Ask for JSON in plain text and parse it: no schema guidance for the model and more ways to fail.
- Let the model write the response text and check it afterwards: free text cannot be checked deterministically.
- Drop only the invalid claims and keep the rest: not chosen; a malformed output points to a model problem, and rejecting all of it is simpler and safer.
- Enforce value formats in the drafter schema too: would duplicate the verifier's rules and let them drift.
#### Consequences
- The forced `toolChoice` and the generated schema (a discriminated union with `$ref`s inlined) were verified only for `us.anthropic.claude-sonnet-4-6` and `us.anthropic.claude-haiku-4-5-20251001-v1:0`, in three live runs on 2026-11-10 (PROGRESS.md). Behaviour on any other model is unverified; changing `BEDROCK_MODEL_ID` needs a new live check. If a model refuses a forced tool, the call fails as a `ModelCallError`; it does not fall back silently.
- Fencing buyer messages reduces prompt-injection risk but cannot rule it out. Safety rests on the schema, the verifier, rendering only VERIFIED claims and merchant approval. No live run has put an injection in front of the real model; offline tests show that manipulated claims are blocked or flagged.
- A VERIFIED claim means the model copied a value that matches PayPal or the merchant record. It says nothing about whether the response would win the dispute. Model accuracy is measured in T-007.
- Every live drafter run is a billed Bedrock call.

### ADR-010: Send path: VERIFIED-only rendering, re-verify on approve, local dry-by-default app
- Date: 2026-11-10
- Status: Accepted
- Supersedes: none

#### Context
T-006 adds the approval page and the only path that writes to PayPal on the merchant's behalf. ADR-009 decided that the text sent to PayPal is rendered by a template from VERIFIED claims only and left the template to T-006. PROGRESS.md "Next steps" (end of T-005) suggested that FLAGGED claims could be sent if the merchant confirmed each one; that is replaced here. Facts from the sandbox that shape the gate: provide-evidence was accepted only when PayPal offered the `provide_evidence` link (T-002, T-003); `allowed_response_options` was present in states where that link was not offered, and its content was never inspected; only carrier `FEDEX` has been sent as `carrier_name`, which PayPal documents as an enum.
#### Decision
- **What can be sent.** Only VERIFIED claims reach the response. FLAGGED and BLOCKED claims are shown to the merchant with their reasons but never rendered or sent, and the merchant cannot override a verdict.
- **Renderer.** A pure function `render_notes(results)` in `dispute_defender/response/render.py`. One sentence per VERIFIED claim, in this fixed order, joined with a single space:
  1. `The disputed payment is PayPal transaction {id}.`
  2. `The transaction amount was {value} {currency}.`
  3. `The transaction was made on {date} (UTC).`
  4. `PayPal lists this transaction as eligible for Seller Protection.` (only if the claim is VERIFIED and its value is `true`)
  5. `According to our records, the order was shipped with {carrier}, tracking number {tracking}.` (only if both tracking number and carrier are VERIFIED)

  It returns `None` (nothing to send) when no claim is VERIFIED, when two VERIFIED claims share a type, or when no sentence results.
- **Send gate.** A pure function `prepare_send(dispute, results, shown_hash)` in `dispute_defender/response/send.py` returns a send plan or a refusal with a reason. It refuses when: the freshly read dispute does not offer the `provide_evidence` link; the renderer returns `None`; the tracking number or carrier is not VERIFIED; the carrier is not in the fixed carrier list; the notes exceed 2,000 characters; or the SHA-256 of the notes differs from the hash of the text the merchant was shown. The gate uses the link only. `allowed_response_options` is parsed (key names only) and shown for information; it is never a condition.
- **Payload.** `PROOF_OF_FULFILLMENT` with `tracking_info` built from the VERIFIED claim values (never straight from the form) and the rendered notes. No files.
- **Carrier list.** Fixed, `FEDEX` only. Other carriers need their PayPal `carrier_name` enum value checked before they are added.
- **Approve re-verifies.** Approve reads the dispute again, gates on the link before any model call, drafts, verifies and renders again on the server, and sends only if the new text's hash equals the hash the page showed. Verdicts are never read from the browser. On a mismatch nothing is sent and the new draft is shown.
- **Send mode.** `DISPUTE_DEFENDER_SEND_MODE`: `dry` by default and for any value other than `live`. Dry mode runs every step except the provide-evidence POST, and every page says which mode is on.
- **Local app.** Bound to `127.0.0.1` only, with a trusted-host check (`127.0.0.1`, `localhost`). Form posts carry an HMAC CSRF token (per-process random key, 15-minute expiry, single use). Templates autoescape. No persistence: no database, files or sessions.
- **After sending**, the page shows the state read back from PayPal with the read time, never an assumed state.
#### Alternatives
- Let the merchant confirm FLAGGED claims into the response: not chosen; a FLAGGED claim was not checked, and the merchant's click does not check it.
- Gate on `allowed_response_options` too: not chosen; its content was never observed, and it was present where provide-evidence was not offered, so it could refuse every send.
- Send the text approved in the browser instead of re-rendering: not chosen; the browser is not trusted for verdicts or text. The hash only confirms the merchant saw the same text.
- Free-text carrier: not chosen; `carrier_name` is an enum and only `FEDEX` is proven.
- Retry once after a 401 with a new token: moved to its own backlog task (T-011).
#### Consequences
- The response is short and factual; anything the verifier cannot check is left out.
- Approve costs a second billed Bedrock call, and a model that answers differently makes the merchant approve again.
- Only `FEDEX` shipments can be sent until more carriers are checked.
- PayPal's limit on `notes` length and its acceptance of this text are unverified until the live run.
- A sandbox dispute in `WAITING_FOR_SELLER_RESPONSE` with the `provide_evidence` link is needed for the live run; the two known disputes did not offer it at their last read.
#### Notes after implementation (2026-11-10)
- **Check order.** The send gate checks, in this order: the `provide_evidence` link; the tracking number and carrier each VERIFIED exactly once; the carrier in the fixed list; the renderer's output; the 2,000-character limit; the hash. Tracking, carrier and the carrier list are checked before rendering, so an unsupported carrier gets its own refusal reason instead of "nothing to send". The renderer writes the carrier as its canonical list value (`FEDEX`), the same value the payload sends, and writes no shipping sentence for a carrier outside the list.
- **Referrer-Policy.** The app sends `Referrer-Policy: same-origin`, not `no-referrer`. With `no-referrer`, browsers serialize the `Origin` of the page's own form POSTs as `null` (Fetch spec), and the Origin check refused the merchant's Draft click with 403. A real Chrome run found this; the TestClient tests had not. `same-origin` makes the app's own posts carry the real origin and still sends nothing to other sites. The signed single-use token, the Host allowlist and the refusal of foreign and `null` origins are unchanged.
- **Unknown send outcome.** If the provide-evidence POST times out, the connection drops, PayPal answers 5xx or an unreadable 2xx, or an unexpected error occurs, the page says the outcome is unknown and to check the dispute's state before retrying. It never says nothing was sent. A 4xx keeps the "rejected" wording. No retry is offered, and the approve token is single use.
- **`allowed_response_options`.** In the T-006 live run it held only `accept_claim` while the `provide_evidence` link was offered and provide-evidence was accepted. This confirms the decision to gate on the link only.

### ADR-011: Evaluation scoring definitions for T-007
- Date: 2026-11-10
- Status: Accepted
- Supersedes: none

#### Context
T-007 measures how many wrong claims reach the send step with and without the verifier. The README will quote these numbers, so what counts as an error has to be fixed before any live run and must not be tuned after seeing results. Sandbox disputes need manual buyer steps (ADR-007), so all evaluation data is simulated.
#### Decision
- **Data.** 24 simulated scenarios in `evaluation/scenarios/`, each with `"simulated": true` and a hand-written ground truth for all six claim types: `expect` (a list of accepted values, compared as exact JSON, no normalisation code), `absent` (the fact is missing; the claim must not be made) or `unsupported` (the model may make the claim, but it must not be VERIFIED or sent; used when the merchant record is for another transaction, which the prompt does not show the model). The verifier never computes the ground truth.
- **Per call.** `accepted` (a draft came back), `rejected` (`DraftRejected`) or `error` (any other drafter error). Errors are left out of every rate and counted.
- **Per claim of an accepted draft.** `correct` (value in the accepted list), `wrong_value`, `absent_fact` (claim of an `absent` type) or `unsupported`; plus `duplicate` for the second and later claims of one type. Model errors are `wrong_value`, `absent_fact` and duplicates. Incorrect claims are `wrong_value`, `absent_fact` and `unsupported`. Missing expected claims are reported as coverage, not as errors. Wrong source and unknown type can only appear as `rejected`, because the drafter schema fixes them (ADR-009).
- **Verifier outcome** is the `Verdict` from `verify_claims`; the **send outcome** is the `SendPlan` or `Refusal` from `prepare_send`, with the shown hash taken from `render_notes`. A claim reaches the send step when it is VERIFIED and `prepare_send` returns a plan.
- **Metrics.** M1 model claim error rate (per model, per category, as k/n). M2 counterfactual: incorrect claims in accepted drafts, counted as if every claim were sent unchecked; computed from the same outputs, not a separate experiment, and it keeps schema validation, so it is conservative and understates the verifier's value. M3 incorrect claims VERIFIED, and VERIFIED and in a send plan; reported as observed, never assumed to be 0. M4 correct claims FLAGGED or BLOCKED. M5 drafts rejected before the verifier. M6 variation across repetitions. M7 ground-truth class by verdict, with every disagreement listed.
- **Part B.** Offline fault injection into the scenarios' correct claims, at the claim layer (`verify_claims`, `prepare_send`) and the tool-input layer (`draft_claims` with a scripted client). Faults the verifier cannot catch by design (an altered merchant record) are reported as expected misses; a correct local date near midnight is reported as a known false rejection (ADR-008).
- **Freeze.** Hashes of the scenarios, the scoring module, the prompt and schema modules and the pipeline modules are recorded in `evaluation/frozen.json` before the live run; a live run refuses to start if the current hashes differ from the last freeze. Any change after seeing results is declared in `evaluation/DECLARED_CHANGES.md` and shown in the report.
#### Alternatives
- Score claims by the verifier's verdict: circular; the verifier is what is being measured.
- Normalise values in the scoring code: would duplicate the verifier's rules; equivalent forms are listed in the data instead.
- A separate no-verifier experiment: the same outputs give the counterfactual without extra calls.
#### Consequences
- The numbers describe simulated scenarios written with knowledge of the rules, not real-world accuracy.
- A model value in an unlisted but equivalent form counts as a model error and shows in the disagreements table if VERIFIED.
- Part B's catch rate reflects faults designed against known rules, so a high rate is expected by construction.

### ADR-012: Replay mode for judges: two clients swapped, CLI flag only
- Date: 2026-11-11
- Status: Accepted
- Supersedes: none

#### Context
Judges may have no PayPal sandbox account or AWS credentials, and making an answerable sandbox dispute needs manual buyer steps (ADR-007). ADR-004 allows a replay mode only as a labelled extra that is never the default. No PayPal response in the repo is a recording: the test fixtures and the T-007 scenarios are hand-written, and the T-007 raw results hold the model's claims (type, source, value), not its raw tool input.
#### Decision
- **What is swapped.** Only the two external systems: `ReplayPayPalClient` and `ReplayModelClient` in `dispute_defender/replay/`. The prompt builder, drafter validation, verifier, renderer, send gate, CSRF, escaping and read-back are the real code. Replay needs no credentials and makes no network call.
- **How it is enabled.** Only with the command-line flag `python -m dispute_defender.web --replay`. There is no environment variable for it: `load_send_mode()` still returns only `dry` or `live`, and with `--replay` the app does not read `.env` at all. `create_app()` takes a third mode, `replay`, and refuses to start if replay mode is given real clients or if replay clients are given dry or live mode, so a real client can never sit behind the replay banner.
- **What a send does.** In replay mode Approve calls the replay PayPal client's `provide_evidence`, which keeps the payload in memory and moves that dispute to a hand-written read-back state (`UNDER_REVIEW`, no `provide_evidence` link). The page says the state is replayed, not read from PayPal. Nothing is written to disk.
- **Banner.** Every page shows a REPLAY banner in its own colour, distinct from DRY RUN and LIVE SANDBOX SEND, saying the data is recorded or simulated and nothing leaves the machine.
- **Data.** `dispute_defender/replay/data/replay.json`, labelled `"simulated": true`, with a source label per dispute shown on the page:
  1. Scenario N1 (simulated, hand-written for T-007) with the model output recorded in the T-007 live run (primary model, repetition 1), rebuilt from the recorded claims.
  2. A hand-written dispute in `WAITING_FOR_BUYER_RESPONSE` without the `provide_evidence` link; refused before any model call.
  3. A hand-written dispute based on scenario N2 without `seller_protection_eligible`, with its own transaction ID. Its model output is the recorded N2 output with the transaction ID adapted to this dispute and one SIMULATED injected error (amount 250.00 instead of 25.00), which is BLOCKED. The recorded seller protection claim is kept; because this dispute's data has no `seller_protection_eligible`, the verifier has nothing to check it against and FLAGS it. So a BLOCKED and a FLAGGED claim can be seen.
- **Hygiene.** No real PayPal IDs, names, emails, request IDs or secrets in replay data; a test checks this and checks the data's provenance against `evaluation/scenarios/` and `evaluation/results/raw-2026-11-11.jsonl`.
#### Alternatives
- An environment variable or `.env` setting: not chosen; a stray value could switch the app to fake data without the user noticing.
- A separate entry point (`python -m dispute_defender.replay`): equally safe, but one more command to document; the flag is easier for judges to find.
- Replaying the test fixtures: not chosen; they carry real sandbox IDs.
- A fake "ideal" model that copies the prompt's facts: not chosen; replay shows outputs a real model produced, rebuilt from the recorded claims.
#### Consequences
- Replay shows the flow and the verifier, not PayPal's or the model's real behaviour: no model variation, latency, token counts, API errors or unknown-outcome page.
- The read-back state is hand-written from the T-006 observation, not read.
- State is per process; restarting the app resets it.
- `create_app()` gains a third mode value; dry and live behaviour is unchanged.
