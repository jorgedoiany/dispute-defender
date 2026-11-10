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
