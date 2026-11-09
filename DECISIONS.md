# DECISIONS.md

## Index
- ADR-001: Python with a direct REST client for PayPal (Accepted)
- ADR-002: Pipeline with structured output, not a free-roaming agent (Accepted)
- ADR-003: Claude on Amazon Bedrock as the model (Accepted)
- ADR-004: FastAPI with a simple HTML approval page (Accepted)
- ADR-005: Fallback flow if the sandbox spike fails (Proposed)
- ADR-006: Open-source license (Proposed)

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
The project must call an AI model in code.
#### Decision
Use Claude on Amazon Bedrock. Model ID and credentials setup: TODO, to be recorded in AGENTS.md.
#### Alternatives
Other model providers: not chosen.
#### Consequences
Judges without AWS access cannot run the model path; see the replay mode task (T-010).

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
- Status: Proposed
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
- Status: Proposed
- Supersedes: none

#### Context
The official rules require a public repo with an open-source license visible in the About section.
#### Decision
License not chosen yet. To be decided in T-001.
#### Alternatives
Any OSI-approved license.
#### Consequences
The choice must be visible in the repository's About section.
