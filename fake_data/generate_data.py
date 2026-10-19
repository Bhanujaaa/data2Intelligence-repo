"""
Generate fake bank dataset for rate-gateway demo.
Outputs 5 CSV files to fake_data/output/:
  products.csv, pricing_rules.csv, customers.csv, accounts.csv, test_cases.csv
"""

import csv
import os
from datetime import date, timedelta

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True

TODAY = date(2026, 8, 21)
STALE_DATE = TODAY - timedelta(days=32)


def write_csv(filename, fieldnames, rows):
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {len(rows)} rows → {path}")


# ---------------------------------------------------------------------------
# 1. products.csv
# ---------------------------------------------------------------------------
PRODUCTS = [
    {"product_id": "SAV001", "product_name": "Everyday Savings",         "category": "Deposit",  "rate_basis": "APY"},
    {"product_id": "SAV002", "product_name": "High-Yield Savings",       "category": "Deposit",  "rate_basis": "APY"},
    {"product_id": "CD001",  "product_name": "12-Month CD",              "category": "Deposit",  "rate_basis": "APY"},
    {"product_id": "LOAN001","product_name": "Personal Loan",            "category": "Loan",     "rate_basis": "APR"},
    {"product_id": "LOC001", "product_name": "Personal Line of Credit",  "category": "Loan",     "rate_basis": "APR"},
    {"product_id": "AUTO001","product_name": "Auto Loan",                "category": "Loan",     "rate_basis": "APR"},
    {"product_id": "CARD001","product_name": "Rewards Credit Card",      "category": "Card",     "rate_basis": "APR"},
    {"product_id": "CARD002","product_name": "Cash Back Credit Card",    "category": "Card",     "rate_basis": "APR"},
    {"product_id": "MTG001", "product_name": "30-Year Fixed Mortgage",   "category": "Mortgage", "rate_basis": "APR"},
    {"product_id": "MTG002", "product_name": "15-Year Fixed Mortgage",   "category": "Mortgage", "rate_basis": "APR"},
]

write_csv("products.csv", ["product_id", "product_name", "category", "rate_basis"], PRODUCTS)


# ---------------------------------------------------------------------------
# 2. pricing_rules.csv
# ---------------------------------------------------------------------------
# One deliberately stale row: SAV002 had a higher APY 32 days ago.
PRICING_RULES = [
    # SAV001 — Everyday Savings (APY, tiers by balance)
    {"rule_id": "PR001", "product_id": "SAV001", "tier_condition": "balance < 5000",             "rate": "0.50%", "fee": "$0",  "fee_type": "none",          "effective_date": str(TODAY)},
    {"rule_id": "PR002", "product_id": "SAV001", "tier_condition": "balance >= 5000",            "rate": "0.90%", "fee": "$0",  "fee_type": "none",          "effective_date": str(TODAY)},

    # SAV002 — High-Yield Savings (APY, tiers by balance) + one stale row
    {"rule_id": "PR003", "product_id": "SAV002", "tier_condition": "balance < 10000",            "rate": "3.80%", "fee": "$0",  "fee_type": "none",          "effective_date": str(TODAY)},
    {"rule_id": "PR004", "product_id": "SAV002", "tier_condition": "balance >= 10000",           "rate": "4.20%", "fee": "$0",  "fee_type": "none",          "effective_date": str(TODAY)},
    {"rule_id": "PR004B","product_id": "SAV002", "tier_condition": "balance >= 10000",           "rate": "4.50%", "fee": "$0",  "fee_type": "none",          "effective_date": str(STALE_DATE)},  # STALE — old higher rate

    # CD001 — 12-Month CD (APY, tiers by balance)
    {"rule_id": "PR005", "product_id": "CD001",  "tier_condition": "balance < 10000",            "rate": "4.50%", "fee": "$0",  "fee_type": "none",          "effective_date": str(TODAY)},
    {"rule_id": "PR006", "product_id": "CD001",  "tier_condition": "balance >= 10000",           "rate": "4.85%", "fee": "$0",  "fee_type": "none",          "effective_date": str(TODAY)},

    # LOAN001 — Personal Loan (APR, tiers by credit_score)
    {"rule_id": "PR007", "product_id": "LOAN001","tier_condition": "credit_score >= 740",        "rate": "6.99%", "fee": "$0",  "fee_type": "origination",   "effective_date": str(TODAY)},
    {"rule_id": "PR008", "product_id": "LOAN001","tier_condition": "credit_score 580-739",       "rate": "14.99%","fee": "$50", "fee_type": "origination",   "effective_date": str(TODAY)},
    {"rule_id": "PR009", "product_id": "LOAN001","tier_condition": "credit_score < 580",         "rate": "29.99%","fee": "$75", "fee_type": "origination",   "effective_date": str(TODAY)},

    # LOC001 — Personal Line of Credit (APR, tiers by credit_score)
    {"rule_id": "PR010", "product_id": "LOC001", "tier_condition": "credit_score >= 740",        "rate": "9.50%", "fee": "$0",  "fee_type": "annual",        "effective_date": str(TODAY)},
    {"rule_id": "PR011", "product_id": "LOC001", "tier_condition": "credit_score 580-739",       "rate": "18.00%","fee": "$25", "fee_type": "annual",        "effective_date": str(TODAY)},
    {"rule_id": "PR012", "product_id": "LOC001", "tier_condition": "credit_score < 580",         "rate": "27.00%","fee": "$50", "fee_type": "annual",        "effective_date": str(TODAY)},

    # AUTO001 — Auto Loan (APR, tiers by credit_score)
    {"rule_id": "PR013", "product_id": "AUTO001","tier_condition": "credit_score >= 740",        "rate": "5.25%", "fee": "$0",  "fee_type": "none",          "effective_date": str(TODAY)},
    {"rule_id": "PR014", "product_id": "AUTO001","tier_condition": "credit_score 580-739",       "rate": "9.99%", "fee": "$0",  "fee_type": "none",          "effective_date": str(TODAY)},
    {"rule_id": "PR015", "product_id": "AUTO001","tier_condition": "credit_score < 580",         "rate": "14.75%","fee": "$0",  "fee_type": "none",          "effective_date": str(TODAY)},

    # CARD001 — Rewards Credit Card (APR, intro + standard tiers)
    {"rule_id": "PR016", "product_id": "CARD001","tier_condition": "intro: first 15 billing cycles","rate": "0.00%","fee": "$95","fee_type": "annual",       "effective_date": str(TODAY)},
    {"rule_id": "PR017", "product_id": "CARD001","tier_condition": "standard",                   "rate": "22.99%","fee": "$95", "fee_type": "annual",        "effective_date": str(TODAY)},

    # CARD002 — Cash Back Credit Card (APR, intro + standard tiers)
    {"rule_id": "PR018", "product_id": "CARD002","tier_condition": "intro: first 12 billing cycles","rate": "0.00%","fee": "$0", "fee_type": "annual",       "effective_date": str(TODAY)},
    {"rule_id": "PR019", "product_id": "CARD002","tier_condition": "standard",                   "rate": "20.49%","fee": "$0",  "fee_type": "annual",        "effective_date": str(TODAY)},

    # MTG001 — 30-Year Fixed Mortgage (APR, tiers by credit_score)
    {"rule_id": "PR020", "product_id": "MTG001", "tier_condition": "credit_score >= 740",        "rate": "5.75%", "fee": "$0",  "fee_type": "none",          "effective_date": str(TODAY)},
    {"rule_id": "PR021", "product_id": "MTG001", "tier_condition": "credit_score 580-739",       "rate": "6.50%", "fee": "$0",  "fee_type": "none",          "effective_date": str(TODAY)},
    {"rule_id": "PR022", "product_id": "MTG001", "tier_condition": "credit_score < 580",         "rate": "7.25%", "fee": "$0",  "fee_type": "none",          "effective_date": str(TODAY)},

    # MTG002 — 15-Year Fixed Mortgage (APR, tiers by credit_score)
    {"rule_id": "PR023", "product_id": "MTG002", "tier_condition": "credit_score >= 740",        "rate": "5.50%", "fee": "$0",  "fee_type": "none",          "effective_date": str(TODAY)},
    {"rule_id": "PR024", "product_id": "MTG002", "tier_condition": "credit_score 580-739",       "rate": "6.25%", "fee": "$0",  "fee_type": "none",          "effective_date": str(TODAY)},
    {"rule_id": "PR025", "product_id": "MTG002", "tier_condition": "credit_score < 580",         "rate": "7.00%", "fee": "$0",  "fee_type": "none",          "effective_date": str(TODAY)},
]

write_csv(
    "pricing_rules.csv",
    ["rule_id", "product_id", "tier_condition", "rate", "fee", "fee_type", "effective_date"],
    PRICING_RULES,
)


# ---------------------------------------------------------------------------
# 3. customers.csv
# ---------------------------------------------------------------------------
CUSTOMERS = [
    {"customer_id": "CUST001", "first_name": "Priya",   "last_name": "Nair",      "credit_score": 760, "join_date": "2023-02-14"},  # excellent
    {"customer_id": "CUST002", "first_name": "Marcus",  "last_name": "Webb",      "credit_score": 805, "join_date": "2024-07-03"},  # excellent
    {"customer_id": "CUST003", "first_name": "Sofia",   "last_name": "Reyes",     "credit_score": 680, "join_date": "2023-11-20"},  # good
    {"customer_id": "CUST004", "first_name": "Darius",  "last_name": "Okonkwo",   "credit_score": 610, "join_date": "2024-01-08"},  # good
    {"customer_id": "CUST005", "first_name": "Hannah",  "last_name": "Johansson", "credit_score": 540, "join_date": "2022-05-30"},  # poor
    {"customer_id": "CUST006", "first_name": "Takeshi", "last_name": "Mori",      "credit_score": 555, "join_date": "2022-09-17"},  # poor
    {"customer_id": "CUST007", "first_name": "Leila",   "last_name": "Farrokhzad","credit_score": 720, "join_date": "2023-06-25"},  # good (near-excellent)
    {"customer_id": "CUST008", "first_name": "Jordan",  "last_name": "Bell",      "credit_score": 790, "join_date": "2024-03-12"},  # excellent
    {"customer_id": "CUST009", "first_name": "Amara",   "last_name": "Diallo",    "credit_score": 630, "join_date": "2023-08-01"},  # good
    {"customer_id": "CUST010", "first_name": "Victor",  "last_name": "Rossi",     "credit_score": 750, "join_date": "2022-12-05"},  # excellent (long tenure — grandfathered)
]

write_csv(
    "customers.csv",
    ["customer_id", "first_name", "last_name", "credit_score", "join_date"],
    CUSTOMERS,
)


# ---------------------------------------------------------------------------
# 4. accounts.csv
# Notes on grandfathered accounts (marked GRANDFATHERED):
#   ACC002: CUST001 opened High-Yield Savings in 2023 at 0.30% APY; current rate for <10k tier is 3.80%
#   ACC010: CUST010 opened Personal Loan in 2022 at 5.50% APR; current rate for >=740 tier is 6.99%
#   ACC013: CUST005 opened Auto Loan in 2022 at 8.50% APR; current rate for <580 tier is 14.75%
# ---------------------------------------------------------------------------
ACCOUNTS = [
    {"account_id": "ACC001", "customer_id": "CUST001", "product_id": "SAV001", "opened_date": "2023-02-14", "current_balance": 3200.00,  "rate_locked_in": "0.50%", "status": "active"},
    {"account_id": "ACC002", "customer_id": "CUST001", "product_id": "SAV002", "opened_date": "2023-03-01", "current_balance": 8500.00,  "rate_locked_in": "0.30%", "status": "active"},   # GRANDFATHERED — was 0.30%, now 3.80%
    {"account_id": "ACC003", "customer_id": "CUST002", "product_id": "CARD001","opened_date": "2024-07-10", "current_balance": 0.00,     "rate_locked_in": "22.99%","status": "active"},
    {"account_id": "ACC004", "customer_id": "CUST003", "product_id": "LOAN001","opened_date": "2023-12-05", "current_balance": 12000.00, "rate_locked_in": "14.99%","status": "active"},
    {"account_id": "ACC005", "customer_id": "CUST003", "product_id": "SAV001", "opened_date": "2024-01-15", "current_balance": 1500.00,  "rate_locked_in": "0.50%", "status": "active"},
    {"account_id": "ACC006", "customer_id": "CUST004", "product_id": "AUTO001","opened_date": "2024-02-20", "current_balance": 18750.00, "rate_locked_in": "9.99%", "status": "active"},
    {"account_id": "ACC007", "customer_id": "CUST005", "product_id": "LOAN001","opened_date": "2022-06-10", "current_balance": 4200.00,  "rate_locked_in": "29.99%","status": "active"},
    {"account_id": "ACC008", "customer_id": "CUST005", "product_id": "CARD002","opened_date": "2022-07-01", "current_balance": 650.00,   "rate_locked_in": "20.49%","status": "closed"},   # CLOSED
    {"account_id": "ACC009", "customer_id": "CUST006", "product_id": "LOC001", "opened_date": "2022-10-05", "current_balance": 2000.00,  "rate_locked_in": "27.00%","status": "active"},
    {"account_id": "ACC010", "customer_id": "CUST010", "product_id": "LOAN001","opened_date": "2022-12-20", "current_balance": 9500.00,  "rate_locked_in": "5.50%", "status": "active"},   # GRANDFATHERED — was 5.50%, now 6.99%
    {"account_id": "ACC011", "customer_id": "CUST007", "product_id": "MTG001", "opened_date": "2023-07-15", "current_balance": 285000.00,"rate_locked_in": "6.50%", "status": "active"},
    {"account_id": "ACC012", "customer_id": "CUST008", "product_id": "SAV002", "opened_date": "2024-04-01", "current_balance": 15000.00, "rate_locked_in": "4.20%", "status": "active"},
    {"account_id": "ACC013", "customer_id": "CUST005", "product_id": "AUTO001","opened_date": "2022-08-12", "current_balance": 6300.00,  "rate_locked_in": "8.50%", "status": "active"},   # GRANDFATHERED — was 8.50%, now 14.75%
    {"account_id": "ACC014", "customer_id": "CUST009", "product_id": "CD001",  "opened_date": "2024-06-01", "current_balance": 5000.00,  "rate_locked_in": "4.50%", "status": "active"},
    {"account_id": "ACC015", "customer_id": "CUST008", "product_id": "CARD002","opened_date": "2024-05-01", "current_balance": 200.00,   "rate_locked_in": "20.49%","status": "active"},
]

write_csv(
    "accounts.csv",
    ["account_id", "customer_id", "product_id", "opened_date", "current_balance", "rate_locked_in", "status"],
    ACCOUNTS,
)


# ---------------------------------------------------------------------------
# 5. test_cases.csv
# ---------------------------------------------------------------------------
TEST_CASES = [
    # --- correct_baseline (2-3): bot quotes right rate for a general product question → PASS
    {
        "id": "TC001",
        "customer_id": "",
        "customer_question": "What is the current APY on the High-Yield Savings account if I deposit $12,000?",
        "bot_response": "For balances of $10,000 or more, our High-Yield Savings account currently earns 4.20% APY.",
        "expected_gateway_action": "PASS",
        "scenario_type": "correct_baseline",
    },
    {
        "id": "TC002",
        "customer_id": "",
        "customer_question": "What's the APR on a Personal Loan for someone with a 760 credit score?",
        "bot_response": "Customers with a credit score of 740 or above qualify for a Personal Loan at 6.99% APR.",
        "expected_gateway_action": "PASS",
        "scenario_type": "correct_baseline",
    },
    {
        "id": "TC003",
        "customer_id": "",
        "customer_question": "What's the intro APR on the Cash Back Credit Card?",
        "bot_response": "The Cash Back Credit Card offers a 0.00% APR intro rate for the first 12 billing cycles, with no annual fee.",
        "expected_gateway_action": "PASS",
        "scenario_type": "correct_baseline",
    },

    # --- wrong_tier (2-3): bot quotes wrong tier's rate for customer's actual credit score → CORRECT
    {
        "id": "TC004",
        "customer_id": "CUST003",
        "customer_question": "What APR would I get on a Personal Loan?",
        "bot_response": "With your profile, you'd qualify for our best Personal Loan rate of 6.99% APR.",
        "expected_gateway_action": "CORRECT",
        "scenario_type": "wrong_tier",
    },
    {
        "id": "TC005",
        "customer_id": "CUST005",
        "customer_question": "What rate could I get on an Auto Loan?",
        "bot_response": "You'd be looking at 9.99% APR for an Auto Loan.",
        "expected_gateway_action": "CORRECT",
        "scenario_type": "wrong_tier",
    },
    {
        "id": "TC006",
        "customer_id": "CUST004",
        "customer_question": "What APR would I qualify for on a Personal Line of Credit?",
        "bot_response": "Customers with your credit profile qualify for our lowest Personal Line of Credit rate of 9.50% APR with no annual fee.",
        "expected_gateway_action": "CORRECT",
        "scenario_type": "wrong_tier",
    },

    # --- product_confusion (2): bot mixes up similarly-named products → CORRECT
    {
        "id": "TC007",
        "customer_id": "",
        "customer_question": "What rate does the Personal Loan carry for good credit?",
        "bot_response": "Our Personal Line of Credit for customers with 580-739 credit scores is 18.00% APR.",
        "expected_gateway_action": "CORRECT",
        "scenario_type": "product_confusion",
    },
    {
        "id": "TC008",
        "customer_id": "",
        "customer_question": "What is the APY on the Everyday Savings account for a $500 balance?",
        "bot_response": "The High-Yield Savings account offers 3.80% APY for balances under $10,000.",
        "expected_gateway_action": "CORRECT",
        "scenario_type": "product_confusion",
    },

    # --- rate_basis_confusion (2): bot states APR when it should be APY, or vice versa → CORRECT
    {
        "id": "TC009",
        "customer_id": "",
        "customer_question": "What's the annual return on a 12-Month CD with $15,000?",
        "bot_response": "A 12-Month CD with $15,000 earns 4.85% APR for balances of $10,000 and above.",
        "expected_gateway_action": "CORRECT",
        "scenario_type": "rate_basis_confusion",
    },
    {
        "id": "TC010",
        "customer_id": "",
        "customer_question": "What's the rate on the 30-Year Fixed Mortgage for excellent credit?",
        "bot_response": "For a credit score of 740 or above, our 30-Year Fixed Mortgage has a rate of 5.75% APY.",
        "expected_gateway_action": "CORRECT",
        "scenario_type": "rate_basis_confusion",
    },

    # --- stale_rate (2): bot quotes old rate from the stale pricing row → CORRECT
    {
        "id": "TC011",
        "customer_id": "",
        "customer_question": "What APY does the High-Yield Savings offer for balances over $10,000?",
        "bot_response": "High-Yield Savings accounts with $10,000 or more currently earn 4.50% APY.",
        "expected_gateway_action": "CORRECT",
        "scenario_type": "stale_rate",
    },
    {
        "id": "TC012",
        "customer_id": "",
        "customer_question": "I heard the High-Yield Savings rate just changed. What is it now for large balances?",
        "bot_response": "Yes, the rate for balances over $10,000 is 4.50% APY as of last month.",
        "expected_gateway_action": "CORRECT",
        "scenario_type": "stale_rate",
    },

    # --- unknown_product (2): product not in catalog → FALLBACK
    {
        "id": "TC013",
        "customer_id": "",
        "customer_question": "What is the rate on your Money Market account?",
        "bot_response": "Our Money Market account currently offers 3.10% APY.",
        "expected_gateway_action": "FALLBACK",
        "scenario_type": "unknown_product",
    },
    {
        "id": "TC014",
        "customer_id": "",
        "customer_question": "Do you offer a jumbo mortgage and what's the rate?",
        "bot_response": "Our Jumbo Mortgage starts at 6.25% APR for qualifying borrowers.",
        "expected_gateway_action": "FALLBACK",
        "scenario_type": "unknown_product",
    },

    # --- unknown_tier_combo (2): product exists but no matching tier → FALLBACK
    {
        "id": "TC015",
        "customer_id": "CUST005",
        "customer_question": "Can I get a 15-Year Fixed Mortgage and what would my rate be?",
        "bot_response": "You can certainly apply for a 15-Year Fixed Mortgage.",
        "expected_gateway_action": "FALLBACK",
        "scenario_type": "unknown_tier_combo",
    },
    {
        "id": "TC016",
        "customer_id": "",
        "customer_question": "What's the CD rate for a $500 deposit for just 3 months?",
        "bot_response": "We offer a short-term CD at 2.50% APY for 3-month terms.",
        "expected_gateway_action": "FALLBACK",
        "scenario_type": "unknown_tier_combo",
    },

    # --- ambiguous_reference (2): customer says "my loan" but holds multiple matching accounts → FALLBACK
    {
        "id": "TC017",
        "customer_id": "CUST005",
        "customer_question": "What's the current rate on my loan?",
        "bot_response": "Your loan is currently at 29.99% APR.",
        "expected_gateway_action": "FALLBACK",
        "scenario_type": "ambiguous_reference",
    },
    {
        "id": "TC018",
        "customer_id": "CUST008",
        "customer_question": "What are the fees on my card?",
        "bot_response": "Your credit card has no annual fee.",
        "expected_gateway_action": "FALLBACK",
        "scenario_type": "ambiguous_reference",
    },

    # --- multi_claim (2): bot states two claims in one sentence → test multi-claim extraction
    {
        "id": "TC019",
        "customer_id": "",
        "customer_question": "What are the rates and fees on a Personal Loan for a 700 credit score?",
        "bot_response": "For a 700 credit score, the Personal Loan carries 14.99% APR with a $50 origination fee.",
        "expected_gateway_action": "PASS",
        "scenario_type": "multi_claim",
    },
    {
        "id": "TC020",
        "customer_id": "",
        "customer_question": "What's the standard APR and annual fee on the Rewards Credit Card?",
        "bot_response": "The Rewards Credit Card has a standard APR of 22.99% and a $95 annual fee.",
        "expected_gateway_action": "PASS",
        "scenario_type": "multi_claim",
    },

    # --- no_claim (2): bot response has no rate/fee numbers → PASS with nothing to verify
    {
        "id": "TC021",
        "customer_id": "",
        "customer_question": "How do I open a savings account?",
        "bot_response": "You can open a savings account online, via our mobile app, or at any branch. You'll need a government-issued ID and a minimum opening deposit.",
        "expected_gateway_action": "PASS",
        "scenario_type": "no_claim",
    },
    {
        "id": "TC022",
        "customer_id": "",
        "customer_question": "What documents do I need to apply for a mortgage?",
        "bot_response": "You'll typically need proof of income, recent bank statements, tax returns, and a government-issued ID to apply for a mortgage.",
        "expected_gateway_action": "PASS",
        "scenario_type": "no_claim",
    },

    # --- my_account_lookup (3): customer asks about their own account → gateway checks accounts.csv → PASS
    {
        "id": "TC023",
        "customer_id": "CUST001",
        "customer_question": "What APY am I currently earning on my Everyday Savings?",
        "bot_response": "Your Everyday Savings account is earning 0.50% APY.",
        "expected_gateway_action": "PASS",
        "scenario_type": "my_account_lookup",
    },
    {
        "id": "TC024",
        "customer_id": "CUST004",
        "customer_question": "What's the APR on my Auto Loan?",
        "bot_response": "Your Auto Loan is currently at 9.99% APR.",
        "expected_gateway_action": "PASS",
        "scenario_type": "my_account_lookup",
    },
    {
        "id": "TC025",
        "customer_id": "CUST007",
        "customer_question": "Can you confirm the rate on my mortgage?",
        "bot_response": "Your 30-Year Fixed Mortgage is locked in at 6.50% APR.",
        "expected_gateway_action": "PASS",
        "scenario_type": "my_account_lookup",
    },

    # --- grandfathered_rate (2): bot "corrects" customer's real locked-in rate to today's catalog rate → PASS
    # Gateway must NOT flag these as errors — the customer's actual rate is legitimately different
    {
        "id": "TC026",
        "customer_id": "CUST001",
        "customer_question": "My High-Yield Savings is only showing 0.30% APY. Isn't the current rate higher?",
        "bot_response": "You're right — the current rate for that tier is 3.80% APY. Your account should be updated to the current rate.",
        "expected_gateway_action": "PASS",
        "scenario_type": "grandfathered_rate",
    },
    {
        "id": "TC027",
        "customer_id": "CUST010",
        "customer_question": "What's the interest rate on my Personal Loan?",
        "bot_response": "The current Personal Loan rate for your credit tier is 6.99% APR.",
        "expected_gateway_action": "PASS",
        "scenario_type": "grandfathered_rate",
    },

    # --- closed_account (1): bot quotes a rate for a closed account → CORRECT/FALLBACK
    {
        "id": "TC028",
        "customer_id": "CUST005",
        "customer_question": "What's the APR on my Cash Back Credit Card?",
        "bot_response": "Your Cash Back Credit Card has a standard APR of 20.49%.",
        "expected_gateway_action": "CORRECT",
        "scenario_type": "closed_account",
    },
]

write_csv(
    "test_cases.csv",
    ["id", "customer_id", "customer_question", "bot_response", "expected_gateway_action", "scenario_type"],
    TEST_CASES,
)

print(f"\nAll files written to: {OUTPUT_DIR}")
