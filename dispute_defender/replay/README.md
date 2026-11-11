# Replay mode (T-010, ADR-012)

Run the approval page without PayPal or AWS credentials and without network access:

```
.venv/bin/python -m dispute_defender.web --replay [--port N]
```

Then open `http://127.0.0.1:8000`. Every page shows a blue **REPLAY** banner. Replay
is turned on only by the `--replay` flag: no environment variable or `.env` line does,
and with the flag the app does not read `.env` at all.

## What is real and what is replayed

Replay swaps only the two external systems:

| Part | In replay mode |
|---|---|
| PayPal client | `ReplayPayPalClient`: serves the disputes in `data/replay.json`; "provide-evidence" keeps the payload in memory and moves the dispute to a hand-written `UNDER_REVIEW` state |
| Model client (Bedrock) | `ReplayModelClient`: returns the dispute's model output from `data/replay.json` as a `submit_claims` tool call |
| Prompt builder, drafter validation, verifier, renderer, send gate, CSRF, escaping, read-back | The real code, unchanged |

Nothing is sent anywhere and nothing is written to disk. Restarting the app resets the state.

## The three disputes

| Dispute | What to type | What you see |
|---|---|---|
| `PP-R-SIM-N1` | tracking `SIM100000001`, carrier `FEDEX` | 6 claims VERIFIED; Approve records the evidence locally; the replayed state is `UNDER_REVIEW` and a second response is refused |
| `PP-R-SIM-REPLAY2` | nothing (no form) | Refused: the dispute is waiting for the buyer and offers no `provide_evidence` link; no model output is used |
| `PP-R-SIM-REPLAY3` | tracking `SIM100000002`, carrier `FEDEX` | Amount BLOCKED (injected error), seller protection FLAGGED, the other 4 VERIFIED; the response leaves both out and can still be approved |

Any other tracking number makes the verifier block the tracking claim, and the send
gate then refuses the whole response.

## Where the data comes from

All of it is in `data/replay.json`, labelled `"simulated": true`, and each dispute's
sources are shown on its page.

- **Disputes: hand-written, sandbox-shaped, SIMULATED.** Dispute 1 is scenario N1 of
  the T-007 evaluation (`evaluation/scenarios/N1.json`), unchanged. Disputes 2 and 3 were
  hand-written for T-010, based on scenarios N3 and N2. None of them is a recording of
  a PayPal response, and none is a real dispute.
- **Model outputs: recorded on simulated scenarios.** Claims that
  `us.anthropic.claude-sonnet-4-6` made on scenarios N1 and N2 in the T-007 live run on
  2026-11-11 (repetition 1), rebuilt into tool-input shape from the recorded claim values
  in `evaluation/results/raw-2026-11-11.jsonl`. The raw results store each claim's type,
  source and value, not the model's raw tool input.
- **Dispute 3 is changed on purpose.** Its recorded `transaction_id` claim is changed to
  match the replay dispute's own transaction ID, and its amount claim is changed from
  25.00 USD to 250.00 USD: a **SIMULATED model error injected to demonstrate the
  verifier**. The seller protection claim is the recorded one; the replay dispute leaves
  out `seller_protection_eligible`, so there is nothing to check it against and it is FLAGGED.
- **Read-back after a send** is hand-written: `UNDER_REVIEW` with only the `self` link,
  as observed in the live sandbox after evidence in T-006.

The data holds no real PayPal IDs, names, emails, request IDs or secrets.
`tests/test_replay_data.py` checks this and checks the provenance above against the
scenarios and the raw results.

## Limits

- No PayPal response here is a recording; all are hand-written.
- Replay does not show model variation, latency, token counts or API errors (no 5xx
  and no unknown-outcome page).
- The refusal text for dispute 2 is the real send gate's wording ("PayPal does not
  offer provide-evidence ..."); in replay the "PayPal" there means the replay data.
- PayPal's acceptance of the payload is shown only by the live T-006 run, not here.
- One process, in memory: restart to reset; concurrent use is not considered.
