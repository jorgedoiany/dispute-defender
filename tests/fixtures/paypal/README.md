# PayPal test fixtures

These JSON files are **hand-written**, not recorded PayPal responses. They follow the
shapes and values observed in the T-002 sandbox spike (see PROGRESS.md): sandbox
dispute `PP-R-HBV-10197617`, reason `MERCHANDISE_OR_SERVICE_NOT_RECEIVED`, 10.00 USD,
the statuses, stages and link names seen in each step, and the
`ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE` error with debug_id `f41195223259c`.

Fields the spike did not print (timestamps, buyer and seller details, messages, the
OAuth `app_id` and `nonce`) are placeholders. Buyer fields use `FAKE-...` values so the
tests can check they never reach models or error messages. The access token is fake.

`dispute_inquiry_waiting.json` also has placeholder values for the transaction fields
the claim verifier reads (T-004): `create_time`, `gross_amount`, `transaction_status`
and `seller_protection_eligible`. Only the key names were observed in the sandbox; the
value formats follow PayPal's documentation and have not been checked against a live
response. The capture amount (10.00 USD) and `seller_transaction_id` (the T-002 capture
ID) match the spike. The other dispute fixtures leave these fields out on purpose.
