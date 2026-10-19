# Fake Data Generation — Instructions

## What this covers
This is scoped to **generating the fake dataset only** — the fictional bank's product catalog, tiered pricing rules, and test bot responses. It does not cover building the gateway/verification logic itself; that's a separate step for later.

## Why a generator script instead of hand-typed CSVs
Reproducible (anyone on the team can regenerate the same or expanded dataset), easy to tweak (change a rate range, add a product, rerun), and it's a small, safe, well-scoped task to hand to Claude Code.

## Volume (set expectations up front)

This is sized to be a **realistic-shaped but small demo dataset**, not production scale:
- `products.csv` — ~10 products
- `pricing_rules.csv` — ~25-30 rows (2-3 tiers × 10 products)
- `customers.csv` — ~8-10 customers
- `accounts.csv` — ~12-15 rows (customers can hold more than one product)
- `test_cases.csv` — ~22-24 rows

Total: roughly **80-90 rows** across all five files. That's still tiny next to a real bank's catalog and customer base — and it should stay tiny. The goal isn't scale, it's **structural realism**: tiered pricing, product ambiguity, stale rates, grandfathered account rates, multi-claim responses, and honest fallbacks all represented at small scale, so the gateway logic that reads this data is the same logic that would work against a real, larger dataset.

## Files to create

```
rate-gateway/
└── data/
    ├── products.csv         # product catalog (generated)
    ├── pricing_rules.csv    # current tiered rates/fees per product (generated)
    ├── customers.csv        # customer directory (generated)
    ├── accounts.csv         # which products each customer actually holds, at what rate (generated)
    └── test_cases.csv       # fake bot responses + expected outcome (generated)
scripts/
└── generate_data.py         # generates all 5 CSVs above — run this first, rerun anytime to regenerate/expand
```

## Build `scripts/generate_data.py`

Ask Claude Code to write a single Python script that generates all five CSVs below using the `csv` or `pandas` module. Run it once to produce the files; rerun anytime to regenerate or expand.

### Output 1: `data/products.csv`
Columns: `product_id, product_name, category, rate_basis`

Requirements:
- 4 categories: `Deposit`, `Loan`, `Card`, `Mortgage`
- 10 products total, including at least 2 pairs of similarly-named products on purpose (e.g. "Personal Loan" vs "Personal Line of Credit"; "Everyday Savings" vs "High-Yield Savings") to test disambiguation later
- `rate_basis` is `APY` for Deposit products, `APR` for Loan/Card/Mortgage products (this distinction matters — a bot mixing up APY vs APR is itself a realistic hallucination worth testing)

Example rows:
```
SAV001,Everyday Savings,Deposit,APY
SAV002,High-Yield Savings,Deposit,APY
CD001,12-Month CD,Deposit,APY
LOAN001,Personal Loan,Loan,APR
LOC001,Personal Line of Credit,Loan,APR
AUTO001,Auto Loan,Loan,APR
CARD001,Rewards Credit Card,Card,APR
CARD002,Cash Back Credit Card,Card,APR
MTG001,30-Year Fixed Mortgage,Mortgage,APR
MTG002,15-Year Fixed Mortgage,Mortgage,APR
```

### Output 2: `data/pricing_rules.csv`
Columns: `rule_id, product_id, tier_condition, rate, fee, fee_type, effective_date`

This is the bank's **current, live** rate sheet — "what we'd offer someone today," not what any specific existing customer is actually paying (that's `accounts.csv`, below).

Requirements:
- Each product gets 2-3 tiered rules (not one flat rate), reflecting real-world structure:
  - Deposit products: tiers by `balance` (e.g. `balance < 5000`, `balance >= 25000`)
  - Loan/Auto/Mortgage products: tiers by `credit_score` (e.g. `credit_score >= 740`, `credit_score 580-739`, `credit_score < 580`)
  - Card products: an `intro` tier (first N billing cycles, near 0%) and a `standard` tier
- Use realistic ranges: savings 0.5%–4.2% APY, personal loans 6%–32% APR, auto loans 5%–15% APR, mortgages 5.5%–7.5% APR, credit cards 20%–25% APR (intro tiers near 0%), fees $0–$95
- **Include one deliberately "stale" row**: give one product a second rule with an older `effective_date` (e.g. 30 days back) and a different rate than its current rule. This lets you demo the exact real-world failure mode where a bot trained/cached on old data quotes a rate that *was* correct last month.
- Otherwise, `effective_date` should be the same recent date (e.g. today's date) across rows so you have a clean "current" baseline

### Output 3: `data/customers.csv`
Columns: `customer_id, first_name, last_name, credit_score, join_date`

Requirements:
- 8-10 fictional customers
- Spread `credit_score` across tiers so you can exercise all the pricing tiers in `pricing_rules.csv` (include at least one in each band: excellent ≥740, good 580-739, poor <580)
- `join_date` spread across the last 3 years — this matters for the grandfathered-rate scenario below (older join dates = more likely to be on an outdated rate)

Example row:
```
CUST001,Priya,Nair,760,2023-02-14
```

### Output 4: `data/accounts.csv`
Columns: `account_id, customer_id, product_id, opened_date, current_balance, rate_locked_in, status`

This is the important one for "what's happening with *my* account" questions — it's the customer's **actual** rate, which may or may not match today's `pricing_rules.csv`.

Requirements:
- 12-15 rows — most customers hold 1-2 products, a couple hold 3
- `rate_locked_in` should match the pricing tier the customer qualified for *at `opened_date`*, not necessarily today's rate
- **Include 2-3 deliberately "grandfathered" accounts**: set `rate_locked_in` noticeably different from what `pricing_rules.csv` currently offers for that product/tier (e.g. customer opened a savings account 18 months ago at 0.3% APY, current rate for their tier is now 0.63% APY). This is a realistic and important scenario: a bot must not "correct" a customer's real locked-in rate down to today's catalog rate — that would itself be a hallucination in the other direction.
- `status` is `active` or `closed` (include 1-2 closed accounts to test that the gateway won't quote rates on closed accounts)

### Output 5: `data/test_cases.csv`
Columns: `id, customer_id, customer_question, bot_response, expected_gateway_action, scenario_type`

Note the change from earlier drafts: instead of a raw `customer_context` field, test cases now reference a real `customer_id` from `customers.csv`/`accounts.csv` — this is more realistic (a support bot looks up the logged-in customer's actual record) and it forces the gateway to distinguish between "general product rate" questions and "my account" questions, which need different lookups (`pricing_rules` vs. `accounts`).

- `expected_gateway_action` must be one of: `PASS`, `CORRECT`, `FALLBACK`
- `scenario_type` labels *why* this test case exists — makes it easy to pick specific cases for the live demo and to prove coverage to judges

Include a mix of ~22-24 rows across these scenario types:

| scenario_type | count | purpose |
|---|---|---|
| `correct_baseline` | 2-3 | bot answer matches the correct current tiered rate (general product question, no specific customer context needed) → `PASS` |
| `wrong_tier` | 2-3 | bot quotes the wrong tier's rate for the customer's actual credit score/balance → `CORRECT` |
| `product_confusion` | 2 | bot mixes up two similarly-named products → `CORRECT` |
| `rate_basis_confusion` | 1-2 | bot states an APR figure when the product/question was about APY, or vice versa → `CORRECT` |
| `stale_rate` | 2 | bot quotes the old rate from the deliberately-stale pricing row instead of the current one → `CORRECT` |
| `unknown_product` | 2 | customer asks about a product not in the catalog at all → `FALLBACK` |
| `unknown_tier_combo` | 1-2 | product exists but customer's context doesn't match any defined tier → `FALLBACK` |
| `ambiguous_reference` | 2 | customer says "my loan" / "the card" without naming which product, and holds more than one matching account → `FALLBACK` (clarification needed) |
| `multi_claim` | 2 | bot response states two claims in one sentence (e.g. "9.2% APR with a $50 origination fee") → tests that extraction/verification handles more than one claim per response |
| `no_claim` | 1-2 | bot response contains no rate/fee numbers at all → `PASS` with nothing to verify — proves the gateway doesn't over-flag non-financial statements |
| `my_account_lookup` | 2-3 | customer asks about *their own* account rate/balance — gateway must check `accounts.csv` for that customer, not the general `pricing_rules.csv` → `PASS` if bot correctly states their actual locked-in rate |
| `grandfathered_rate` | 2 | bot incorrectly "corrects" a customer's real locked-in rate to today's catalog rate — gateway must recognize the customer's actual rate is legitimately different and not flag it as an error → `PASS` (this is the trickiest, most impressive scenario to demo — it shows the gateway isn't just naively diffing against one table) |
| `closed_account` | 1 | bot quotes a rate for an account that's actually closed → `FALLBACK` or `CORRECT` (flag that the account is closed) |

## Decisions already made (don't re-litigate mid-build)
- Scope: **rates and fees only**, no eligibility-rule fields
- Data is **tiered, not flat** — deposit rates vary by balance, loan/card/mortgage rates vary by credit score, cards have intro vs. standard tiers
- Two distinct sources of truth: `pricing_rules.csv` (what we'd offer *today*) vs. `accounts.csv` (what an *existing customer* actually locked in) — the gateway must know which one applies depending on whether the question is general or account-specific
- Dataset is **intentionally small but structurally realistic** — covers the failure modes a real gateway would need to handle (stale rates, ambiguity, multi-claim, grandfathered rates, false positives), not full catalog/customer-base scale
- Data format: plain CSV files, no database
- Values are realistic-looking but fictional — not pulled from any real bank's actual disclosures or any real person's data

## After this is done
Once these three CSVs exist and look right, the next phase (not covered here) is building the extraction/verification/gateway logic that reads them.
