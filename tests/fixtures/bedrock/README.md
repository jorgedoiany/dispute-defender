# Bedrock test fixtures

These JSON files are **hand-written**, not recorded Bedrock responses. They follow the
Converse response shape in botocore 1.44.0's service model (`output.message.content[]`
with a `toolUse` block, `stopReason`, `usage`, `metrics`). The claim values match the
hand-written PayPal fixture `../paypal/dispute_inquiry_waiting.json` and the test
merchant record used in the tests. Token counts, latency and IDs are placeholders.
No live Bedrock response had been seen when they were written (T-005).
