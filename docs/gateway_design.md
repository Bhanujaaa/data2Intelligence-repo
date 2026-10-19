# Gateway design

The gateway takes a chatbot answer, works out which rate and fee claims it
makes and which product and tier they refer to (using an LLM), checks those
claims against the bank's data (deterministic, no LLM), and passes, corrects
or falls back with a full audit trail.

## Where the LLM is used, and where it is not

| Step | Uses an LLM? | Why |
|---|---|---|
| 1. Extract claims (which numbers did the answer state?) | **Yes** | Handles natural phrasing a regex would miss ("just over nine percent" vs "9.2%") |
| 2. Match product and tier (which product and customer tier does each claim refer to?) | **Yes** | Resolves fuzzy references ("my loan", "the good rate") better than string matching |
| 3. Verify (does the claimed number match the correct value?) | **No** | The compliance-critical comparison: a strict, auditable lookup plus tolerance check that can be explained to a compliance team |
| 4. Decide action (PASS / CORRECT / FALLBACK) | **No** | Follows from step 3 through fixed rules |
| 5. Log | **No** | One audit row per claim |

## Modules

```
gateway/
├── extract_and_match.py   # LLM call: claims + product/tier in one step
├── verify.py              # deterministic comparison against golden_dataset/
├── trust_signals.py       # provenance, reliability, freshness, cross-source agreement
├── pii.py                 # PII masking before any LLM call, log or response
├── gateway.py             # orchestrator; writes the audit log
└── demo.py                # terminal demo: ask the chatbot, then verify
```

### `extract_and_match.py`

```python
def extract_and_match(bot_response: str, customer_question: str, customer_id: str) -> list[dict]:
```

One LLM call does extraction and matching together, which saves a round trip
and gives the model full context to resolve ambiguity. The prompt includes the
answer text, the customer's question, the products the customer holds (from
`accounts.csv`) and the full `products.csv` list. The model returns JSON only,
for example:

```json
[{
  "claim_text": "9.2% APR",
  "claim_type": "rate",
  "value": 9.2,
  "matched_product_id": "LOAN001",
  "match_confidence": "high",
  "match_reasoning": "customer referred to 'my loan' and holds one loan product"
}]
```

If the call fails or returns unparseable JSON, the result is treated as "no
claims extracted" and escalated to FALLBACK. A `low` match confidence or an
unresolved product also routes to FALLBACK; the gateway never guesses.

### `verify.py`

```python
def verify_claim(claim: dict, customer_id: str) -> dict:
    # -> {"action": "PASS" | "CORRECT" | "FALLBACK", "correct_value": ..., "reason": ...}
```

Plain lookups and comparisons:

1. `matched_product_id` missing or `match_confidence` low → FALLBACK.
2. Account-specific question about a product the customer holds → compare
   against `rate_locked_in` in `accounts.csv`. Grandfathered rates differ from
   today's `pricing_rules.csv` by design, so only the customer's own row counts.
3. Otherwise resolve the tier in `pricing_rules.csv` from the customer's credit
   score or balance and compare within tolerance.
4. No matching product or tier → FALLBACK.
5. Within tolerance → PASS; outside → CORRECT with the right value attached.

### `gateway.py`

1. `extract_and_match()` (LLM)
2. `verify_claim()` for each claim (rules)
3. Any CORRECT → replace that number in the answer with the correct value
4. Any FALLBACK → replace the whole answer with a safe message
   ("Let me get you the current, accurate number on that.")
5. Write one audit row per claim (CSV locally, DynamoDB on AWS)

## Rules

- The LLM is used only for extraction and matching. Verification and the
  PASS / CORRECT / FALLBACK decision are deterministic.
- Any LLM failure (API error, bad JSON, low confidence) results in FALLBACK,
  never a silent pass-through.
- Tolerance: ±0.1% for rates, ±$1 for fees.
- Grandfathered accounts are checked against `accounts.csv`, not
  `pricing_rules.csv`.
