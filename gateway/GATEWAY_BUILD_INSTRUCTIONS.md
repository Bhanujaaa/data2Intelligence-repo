# Gateway Build Instructions

## What this covers
Building the actual gateway: takes a bot response, figures out what financial claims it makes and which product/tier they refer to (using an LLM), checks those claims against your data (deterministic — no LLM), and corrects or falls back with a full audit trail.

## Where the LLM fits — and where it deliberately doesn't

| Step | Uses LLM? | Why |
|---|---|---|
| 1. Extract claims (what numbers/claims did the bot state?) | **Yes** | Handles natural phrasing regex would miss ("just over nine percent" vs "9.2%") |
| 2. Match product/tier (which product and customer tier does this refer to?) | **Yes** | Resolves fuzzy/ambiguous references ("my loan," "the good rate") better than string matching |
| 3. Verify (does the claimed number match the correct value?) | **No — deterministic** | This is the compliance-critical comparison. It must be a strict, auditable rule (exact lookup + tolerance check), not an LLM judgment call — you need to be able to explain and guarantee this step to a bank's compliance team |
| 4. Decide action (pass/correct/fallback) | **No — deterministic** | Follows directly from step 3's result via fixed rules |
| 5. Log | **No** | Just writing a row |

This split is a good story for judges: *"We use AI where understanding language matters, and hard rules where correctness matters — you don't want an LLM deciding whether a compliance check passed."*

## File to create

```
rate-gateway/
└── src/
    ├── extract_and_match.py   # LLM call: claims + product/tier in one step
    ├── verify.py               # deterministic: compare against data, no LLM
    ├── gateway.py              # orchestrates everything, writes audit log
    └── demo.py                 # runs test_cases.csv through the full pipeline
```

## Step 1 — Build `src/extract_and_match.py`

One LLM call that does extraction + matching together (combining them saves a round trip and gives the model full context to resolve ambiguity in one pass).

```python
def extract_and_match(bot_response: str, customer_question: str, customer_id: str) -> list[dict]:
    """
    Calls the LLM once with the bot's response, the customer's question, and 
    that customer's known products/context (pulled from accounts.csv/customers.csv).
    Returns a list of claims found, e.g.:
    [
      {
        "claim_text": "9.2% APR",
        "claim_type": "rate",
        "value": 9.2,
        "matched_product_id": "LOAN001",
        "match_confidence": "high",
        "match_reasoning": "customer referred to 'my loan', customer holds only one loan product"
      }
    ]
    Returns an empty list if no financial claims are found.
    """
```

Requirements:
- Prompt should include: the bot's response text, the customer's original question, the list of that customer's actual held products (from `accounts.csv`) so the model has real context to resolve "my loan" style references, and the full `products.csv` list so it can match general (non-account-specific) questions too
- Ask the LLM to return **structured JSON only** (see the "Structured Outputs" pattern — instruct it clearly to return nothing but JSON, no preamble)
- Always wrap the LLM call in try/except with a fallback: if the call fails or returns unparseable JSON, treat it as "no claims extracted, escalate to FALLBACK" rather than crashing — never let an LLM failure silently pass an unverified claim through
- If `match_confidence` comes back `"low"` or the model can't determine a product, that itself should route to the `ambiguous_reference` fallback path — don't force a guess

## Step 2 — Build `src/verify.py` (no LLM — keep this simple and strict)

```python
def verify_claim(claim: dict, customer_id: str) -> dict:
    """
    Takes one claim from extract_and_match() and checks it deterministically against:
    - accounts.csv (if the question was about the customer's own account)
    - pricing_rules.csv (if it was a general product question)
    Returns: {"action": "PASS" | "CORRECT" | "FALLBACK", "correct_value": ..., "reason": ...}
    """
```

Logic (plain lookups and comparisons, no LLM):
1. If `matched_product_id` is missing or `match_confidence` was low → `FALLBACK`
2. If the customer holds that product in `accounts.csv` and the question was account-specific → compare claim value to `rate_locked_in` (this is the grandfathered-rate check — a mismatch here vs. `pricing_rules.csv` is *expected and fine*, only compare against the customer's own `accounts.csv` row)
3. Otherwise, resolve the tier from `pricing_rules.csv` using the customer's `credit_score`/relevant attribute, and compare against that tier's rate/fee within tolerance (±0.1% rate, ±$1 fee)
4. No matching tier or product found → `FALLBACK`
5. Value matches within tolerance → `PASS`; value doesn't match → `CORRECT` with the right value attached

## Step 3 — Build `src/gateway.py`

Orchestrates the pipeline:
1. Call `extract_and_match()` (LLM step)
2. For each claim returned, call `verify_claim()` (deterministic step)
3. If any claim is `CORRECT` → replace that number in the response text with the correct value
4. If any claim is `FALLBACK` → replace the whole response with a safe templated message (e.g. "Let me get you the current, accurate number on that.")
5. Write one row per claim to `logs/audit_log.csv`: `timestamp, customer_id, original_response, claim_text, matched_product_id, action_taken, correct_value, final_response`

## Step 4 — Build `src/demo.py`

Loop through `test_cases.csv`, run each through `gateway.py`, print a clean before/after comparison — this is what you'll show live.

## Decisions already made (don't re-litigate mid-build)
- **LLM used only for extraction + product/tier matching** — verification and the pass/correct/fallback decision stay 100% deterministic and rule-based
- Any LLM failure (bad response, API error, low confidence) defaults to `FALLBACK`, never a silent pass-through
- Bot stays scripted (from the earlier chatbot setup) — this gateway works the same regardless of whether the response came from the scripted bot or a real one later
- Tolerance: ±0.1% for rates, ±$1 for fees
- Grandfathered accounts are checked against `accounts.csv`, not `pricing_rules.csv` — a mismatch there is not an error
