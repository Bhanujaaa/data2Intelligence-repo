"""
Step 3 — Verification
Compare extracted claims against golden_dataset/pricing_rules.csv
(for general questions) or golden_dataset/accounts.csv (for account-specific
questions).

Returns a verdict dict per claim:
    action          PASS | CORRECT | FALLBACK
    reason          human-readable explanation
    correct_value   the right value (if action is CORRECT)
    correct_basis   the right basis (if action is CORRECT)
"""

import csv
import os
import re

_PROJECT_ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RULES_CSV     = os.path.join(_PROJECT_ROOT, "golden_dataset", "pricing_rules.csv")
_CUSTOMERS_CSV = os.path.join(_PROJECT_ROOT, "golden_dataset", "customers.csv")
_ACCOUNTS_CSV  = os.path.join(_PROJECT_ROOT, "golden_dataset", "accounts.csv")
_PRODUCTS_CSV  = os.path.join(_PROJECT_ROOT, "golden_dataset", "products.csv")

# Vague account reference words that signal "my account" intent
_MY_ACCOUNT_KEYWORDS = [
    "my account", "my loan", "my savings", "my mortgage", "my card",
    "my auto", "my cd", "i am earning", "my rate", "my apr", "my apy",
    "on my", "confirm", "showing",
]

# Category-level keywords for ambiguous reference detection
_CATEGORY_KEYWORDS = {
    "Loan":     ["loan", "borrow", "borrowing"],
    "Card":     ["card", "credit card"],
    "Deposit":  ["savings", "deposit", "account"],
    "Mortgage": ["mortgage", "home loan"],
}


# ── Loaders ────────────────────────────────────────────────────────────

def _load_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _current_rules(product_id: str) -> list[dict]:
    """Return only the most-recent rule rows for a product (drop stale ones)."""
    rules = [r for r in _load_csv(_RULES_CSV) if r["product_id"] == product_id]
    if not rules:
        return []
    latest: dict[str, dict] = {}
    for rule in rules:
        tier = rule["tier_condition"]
        if tier not in latest or rule["effective_date"] > latest[tier]["effective_date"]:
            latest[tier] = rule
    return list(latest.values())


# ── Helpers ────────────────────────────────────────────────────────────

def _tokenize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", text.lower())


def _parse_rate(raw: str) -> float | None:
    m = re.search(r"[\d.]+", raw)
    return float(m.group()) if m else None


def _rate_matches(claimed: float, rule_raw: str, tol: float = 0.001) -> bool:
    expected = _parse_rate(rule_raw)
    return expected is not None and abs(claimed - expected) <= tol


def _fee_matches(claimed: float, rule_raw: str, tol: float = 0.01) -> bool:
    expected = _parse_rate(rule_raw)
    return expected is not None and abs(claimed - expected) <= tol


def _rule_for_customer(rules: list[dict], credit_score: int | None, balance: float | None) -> dict | None:
    """Pick the pricing rule that matches this customer's credit score / balance."""
    score = credit_score or 0
    bal   = balance   or 0.0

    for rule in rules:
        cond = rule["tier_condition"].lower()
        if "credit_score >= 740"  in cond and score >= 740:   return rule
        if "credit_score 580-739" in cond and 580 <= score <= 739: return rule
        if "credit_score < 580"   in cond and score < 580:    return rule
        if "balance < 5000"   in cond and bal < 5000:         return rule
        if "balance >= 25000" in cond and bal >= 25000:        return rule
        if "balance >= 10000" in cond and bal >= 10000:        return rule
        if "balance >= 5000"  in cond and bal >= 5000:         return rule
        if "balance < 10000"  in cond and bal < 10000:         return rule
        if "standard"         in cond:                         return rule
    return None


def _extract_mentioned_credit_score(text: str) -> int | None:
    """Try to parse a credit score explicitly mentioned in the question text."""
    m = re.search(r'\b([3-8]\d{2})\s*(credit\s*score|fico|score)?', text, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if 300 <= val <= 850:
            return val
    return None


def _detect_ambiguous_accounts(
    customer_id:      str,
    product_category: str,
    question:         str,
    matched_product_name: str = "",
) -> bool:
    """
    Return True if the customer holds multiple active accounts in the same category
    AND the question uses a vague reference without naming a specific product.
    """
    if not customer_id:
        return False

    accounts = _load_csv(_ACCOUNTS_CSV)
    products = _load_csv(_PRODUCTS_CSV)
    prod_map = {p["product_id"]: (p["category"], p["product_name"]) for p in products}

    active_in_category = [
        a for a in accounts
        if a["customer_id"] == customer_id
        and a["status"] == "active"
        and prod_map.get(a["product_id"], ("", ""))[0] == product_category
    ]

    if len(active_in_category) <= 1:
        return False

    q_lower = question.lower()

    # Not ambiguous if the question names a specific product from the customer's accounts
    for a in active_in_category:
        cat, name = prod_map.get(a["product_id"], ("", ""))
        name_tokens = [t for t in _tokenize(name).split() if len(t) > 2]
        # If most name tokens appear in the question, the user was specific
        if name_tokens and sum(1 for t in name_tokens if t in q_lower) >= len(name_tokens) - 1:
            return False

    # Check if question uses a vague category word instead of a specific product name
    vague_kws = _CATEGORY_KEYWORDS.get(product_category, [])
    return any(kw in q_lower for kw in vague_kws)


# ── Main verifier ──────────────────────────────────────────────────────

def verify(
    claims:            list[dict],
    product_match:     dict | None,
    customer_id:       str,
    customer_question: str,
    bot_response:      str,
) -> list[dict]:
    """
    Verify each claim and return a verdict list.
    Each verdict: claim, action, reason, correct_value, correct_basis
    """
    verdicts = []

    # ── No claims → nothing to verify ─────────────────────────────────
    if not claims:
        if product_match:
            # Ambiguous product match with no claims → FALLBACK
            if product_match.get("ambiguous"):
                names = ", ".join(c["product_name"] for c in product_match["candidates"])
                verdicts.append({
                    "claim":         None,
                    "action":        "FALLBACK",
                    "reason":        f"Ambiguous product reference — could be: {names}. Clarification needed.",
                    "correct_value": None,
                    "correct_basis": None,
                })
                return verdicts
            # Ambiguous account reference with no claims
            if customer_id:
                category = product_match.get("category", "")
                pname    = product_match.get("product_name", "")
                if _detect_ambiguous_accounts(customer_id, category, customer_question, pname):
                    verdicts.append({
                        "claim":         None,
                        "action":        "FALLBACK",
                        "reason":        f"Ambiguous reference: customer holds multiple active {category} accounts. Clarification needed.",
                        "correct_value": None,
                        "correct_basis": None,
                    })
                    return verdicts
        verdicts.append({
            "claim":         None,
            "action":        "PASS",
            "reason":        "No rate or fee claims found — nothing to verify.",
            "correct_value": None,
            "correct_basis": None,
        })
        return verdicts

    # ── No product identified → FALLBACK ──────────────────────────────
    if product_match is None:
        for claim in claims:
            verdicts.append({
                "claim":         claim,
                "action":        "FALLBACK",
                "reason":        "Product not found in catalog. Cannot verify the rate.",
                "correct_value": None,
                "correct_basis": None,
            })
        return verdicts

    # ── Product confusion → CORRECT ───────────────────────────────────
    if product_match.get("product_confusion"):
        asked    = product_match["asked_product"]["product_name"]
        answered = product_match["answered_product"]["product_name"]
        for claim in claims:
            verdicts.append({
                "claim":         claim,
                "action":        "CORRECT",
                "reason":        f"Product confusion: customer asked about '{asked}' but bot answered about '{answered}'.",
                "correct_value": None,
                "correct_basis": None,
            })
        return verdicts

    # ── Ambiguous product → FALLBACK ──────────────────────────────────
    if product_match.get("ambiguous"):
        names = ", ".join(c["product_name"] for c in product_match["candidates"])
        for claim in claims:
            verdicts.append({
                "claim":         claim,
                "action":        "FALLBACK",
                "reason":        f"Ambiguous product reference — could be: {names}. Clarification needed.",
                "correct_value": None,
                "correct_basis": None,
            })
        return verdicts

    product_id     = product_match["product_id"]
    expected_basis = product_match.get("rate_basis")
    category       = product_match.get("category", "")

    # ── Load customer + account data ──────────────────────────────────
    customer_row = None
    account_row  = None
    is_my_account_question = bool(customer_id) and any(
        kw in customer_question.lower() for kw in _MY_ACCOUNT_KEYWORDS
    )

    # Ambiguous account reference check (with claims present)
    if customer_id and _detect_ambiguous_accounts(customer_id, category, customer_question):
        for claim in claims:
            verdicts.append({
                "claim":         claim,
                "action":        "FALLBACK",
                "reason":        f"Ambiguous reference: customer holds multiple active {category} accounts. Clarification needed.",
                "correct_value": None,
                "correct_basis": None,
            })
        return verdicts

    if customer_id:
        customers = _load_csv(_CUSTOMERS_CSV)
        customer_row = next((c for c in customers if c["customer_id"] == customer_id), None)
        accounts = _load_csv(_ACCOUNTS_CSV)
        matching_accounts = [
            a for a in accounts
            if a["customer_id"] == customer_id and a["product_id"] == product_id
        ]
        if matching_accounts:
            account_row = next(
                (a for a in matching_accounts if a["status"] == "active"),
                matching_accounts[0],
            )
            if account_row["status"] == "closed":
                for claim in claims:
                    verdicts.append({
                        "claim":         claim,
                        "action":        "CORRECT",
                        "reason":        f"Account {account_row['account_id']} is closed. No active rate applies.",
                        "correct_value": None,
                        "correct_basis": None,
                    })
                return verdicts

    # ── Determine credit score to use ─────────────────────────────────
    # Priority: customer record > explicitly stated in question text
    credit_score = int(customer_row["credit_score"]) if customer_row else None
    if credit_score is None:
        credit_score = _extract_mentioned_credit_score(customer_question)

    balance = float(account_row["current_balance"]) if account_row else None

    # ── Load current pricing rules ─────────────────────────────────────
    current_rules = _current_rules(product_id)
    if not current_rules:
        for claim in claims:
            verdicts.append({
                "claim":         claim,
                "action":        "FALLBACK",
                "reason":        f"No pricing rules found for product {product_id}.",
                "correct_value": None,
                "correct_basis": None,
            })
        return verdicts

    applicable_rule = _rule_for_customer(current_rules, credit_score, balance)

    # ── Verify each claim ─────────────────────────────────────────────
    for claim in claims:
        claimed_value = float(claim["value"])
        claimed_basis = claim["basis"]

        # ── Rate claims ───────────────────────────────────────────────
        if claim["type"] == "rate":

            # 1. Rate-basis confusion (APR vs APY)
            if claimed_basis and expected_basis and claimed_basis != expected_basis:
                verdicts.append({
                    "claim":         claim,
                    "action":        "CORRECT",
                    "reason":        f"Rate basis error: bot said {claimed_basis} but this product uses {expected_basis}.",
                    "correct_value": claim["raw"],
                    "correct_basis": expected_basis,
                })
                continue

            # 2. My-account question → check locked-in rate in accounts.csv
            if is_my_account_question and account_row:
                if _rate_matches(claimed_value, account_row["rate_locked_in"]):
                    verdicts.append({
                        "claim":         claim,
                        "action":        "PASS",
                        "reason":        f"Matches customer's locked-in rate {account_row['rate_locked_in']} on account {account_row['account_id']}.",
                        "correct_value": None,
                        "correct_basis": None,
                    })
                else:
                    # Bot quoted today's catalog rate instead of the locked-in rate
                    catalog_match = applicable_rule and _rate_matches(claimed_value, applicable_rule["rate"])
                    locked_rate   = _parse_rate(account_row["rate_locked_in"])
                    if catalog_match and locked_rate is not None:
                        verdicts.append({
                            "claim":         claim,
                            "action":        "PASS",
                            "reason":        (
                                f"Bot quoted today's catalog rate ({applicable_rule['rate']}). "
                                f"Customer's actual locked-in rate is {account_row['rate_locked_in']} — "
                                "both values acknowledged."
                            ),
                            "correct_value": None,
                            "correct_basis": None,
                        })
                    else:
                        correct = account_row["rate_locked_in"] if account_row else (
                            applicable_rule["rate"] if applicable_rule else None
                        )
                        verdicts.append({
                            "claim":         claim,
                            "action":        "CORRECT",
                            "reason":        f"Bot quoted {claim['raw']} but customer's actual locked-in rate is {correct}.",
                            "correct_value": correct,
                            "correct_basis": expected_basis,
                        })
                continue

            # 3. General / catalog question:
            #    No specific customer context → rate is valid if it exists in ANY current tier.
            if not customer_id:
                any_match = next(
                    (r for r in current_rules if _rate_matches(claimed_value, r["rate"])),
                    None,
                )
                if any_match:
                    verdicts.append({
                        "claim":         claim,
                        "action":        "PASS",
                        "reason":        f"Rate {claim['raw']} matches pricing tier '{any_match['tier_condition']}'.",
                        "correct_value": None,
                        "correct_basis": None,
                    })
                else:
                    best = current_rules[0]["rate"] if current_rules else None
                    verdicts.append({
                        "claim":         claim,
                        "action":        "CORRECT",
                        "reason":        f"Rate {claim['raw']} not found in any current pricing tier for {product_match['product_name']}.",
                        "correct_value": best,
                        "correct_basis": expected_basis,
                    })
                continue

            # 4. Customer-contextual question with a determinable tier
            if applicable_rule:
                if _rate_matches(claimed_value, applicable_rule["rate"]):
                    verdicts.append({
                        "claim":         claim,
                        "action":        "PASS",
                        "reason":        f"Rate matches tier '{applicable_rule['tier_condition']}' ({applicable_rule['rate']}).",
                        "correct_value": None,
                        "correct_basis": None,
                    })
                else:
                    wrong_tier = next(
                        (r for r in current_rules if _rate_matches(claimed_value, r["rate"])),
                        None,
                    )
                    if wrong_tier:
                        verdicts.append({
                            "claim":         claim,
                            "action":        "CORRECT",
                            "reason":        (
                                f"Rate {claim['raw']} belongs to tier '{wrong_tier['tier_condition']}' "
                                f"but customer qualifies for '{applicable_rule['tier_condition']}' "
                                f"({applicable_rule['rate']})."
                            ),
                            "correct_value": applicable_rule["rate"],
                            "correct_basis": expected_basis,
                        })
                    else:
                        verdicts.append({
                            "claim":         claim,
                            "action":        "CORRECT",
                            "reason":        f"Rate {claim['raw']} not found in any current tier. Correct: {applicable_rule['rate']}.",
                            "correct_value": applicable_rule["rate"],
                            "correct_basis": expected_basis,
                        })
            else:
                verdicts.append({
                    "claim":         claim,
                    "action":        "FALLBACK",
                    "reason":        "Could not determine an applicable pricing tier for this customer context.",
                    "correct_value": None,
                    "correct_basis": None,
                })

        # ── Fee claims ────────────────────────────────────────────────
        elif claim["type"] == "fee":
            # For general questions, pass if fee exists in any tier
            if not customer_id:
                any_fee_match = next(
                    (r for r in current_rules if _fee_matches(claimed_value, r["fee"])),
                    None,
                )
                if any_fee_match:
                    verdicts.append({
                        "claim":         claim,
                        "action":        "PASS",
                        "reason":        f"Fee {claim['raw']} matches tier '{any_fee_match['tier_condition']}'.",
                        "correct_value": None,
                        "correct_basis": None,
                    })
                else:
                    best_fee = current_rules[0]["fee"] if current_rules else None
                    verdicts.append({
                        "claim":         claim,
                        "action":        "CORRECT",
                        "reason":        f"Fee {claim['raw']} not found in any current tier.",
                        "correct_value": best_fee,
                        "correct_basis": applicable_rule["fee_type"] if applicable_rule else None,
                    })
                continue

            if applicable_rule:
                if _fee_matches(claimed_value, applicable_rule["fee"]):
                    verdicts.append({
                        "claim":         claim,
                        "action":        "PASS",
                        "reason":        f"Fee matches tier '{applicable_rule['tier_condition']}' ({applicable_rule['fee']}).",
                        "correct_value": None,
                        "correct_basis": None,
                    })
                else:
                    verdicts.append({
                        "claim":         claim,
                        "action":        "CORRECT",
                        "reason":        f"Fee {claim['raw']} does not match. Correct: {applicable_rule['fee']} ({applicable_rule['fee_type']}).",
                        "correct_value": applicable_rule["fee"],
                        "correct_basis": applicable_rule["fee_type"],
                    })
            else:
                verdicts.append({
                    "claim":         claim,
                    "action":        "FALLBACK",
                    "reason":        "Cannot determine applicable fee tier for this customer context.",
                    "correct_value": None,
                    "correct_basis": None,
                })

    return verdicts
