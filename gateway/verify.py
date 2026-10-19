"""
Step 3 — Deterministic Verification (no LLM)
=============================================
Takes one claim from extract_and_match() and checks it against the golden dataset.
This step is 100% rule-based — never an LLM judgment call.

Why: a compliance check must be auditable and explainable. You cannot tell a bank's
compliance team "the AI decided the rate was correct."

Tolerance: ±0.1% for rates, ±$1 for fees (see docs/gateway_design.md).
"""

import csv
import os
import re

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GOLDEN_DIR   = os.path.join(_PROJECT_ROOT, "golden_dataset")

RATE_TOLERANCE = 0.1   # ±0.1%
FEE_TOLERANCE  = 1.0   # ±$1


# ── Loaders ────────────────────────────────────────────────────────────

def _load_csv(filename: str) -> list[dict]:
    path = os.path.join(_GOLDEN_DIR, filename)
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _parse_num(raw: str) -> float | None:
    m = re.search(r"[\d.]+", str(raw))
    return float(m.group()) if m else None


# ── Pricing helpers ────────────────────────────────────────────────────

def _current_rules(product_id: str) -> list[dict]:
    """Most-recent pricing rule per tier (stale rows dropped)."""
    rules  = [r for r in _load_csv("pricing_rules.csv") if r["product_id"] == product_id]
    latest: dict[str, dict] = {}
    for rule in rules:
        tier = rule["tier_condition"]
        if tier not in latest or rule["effective_date"] > latest[tier]["effective_date"]:
            latest[tier] = rule
    return list(latest.values())


def _applicable_rule(rules: list[dict], credit_score: int | None, balance: float | None) -> dict | None:
    score = credit_score or 0
    bal   = balance      or 0.0
    for rule in rules:
        cond = rule["tier_condition"].lower()
        if "credit_score >= 740"  in cond and score >= 740:          return rule
        if "credit_score 580-739" in cond and 580 <= score <= 739:   return rule
        if "credit_score < 580"   in cond and score < 580:           return rule
        if "balance >= 25000"     in cond and bal >= 25000:           return rule
        if "balance >= 10000"     in cond and bal >= 10000:           return rule
        if "balance >= 5000"      in cond and bal >= 5000:            return rule
        if "balance < 10000"      in cond and bal < 10000:            return rule
        if "balance < 5000"       in cond and bal < 5000:             return rule
        if "standard"             in cond:                            return rule
        if "intro"                in cond:                            return rule
    return None


def _rate_ok(claimed: float, rule_raw: str) -> bool:
    expected = _parse_num(rule_raw)
    return expected is not None and abs(claimed - expected) <= RATE_TOLERANCE


def _fee_ok(claimed: float, rule_raw: str) -> bool:
    expected = _parse_num(rule_raw)
    return expected is not None and abs(claimed - expected) <= FEE_TOLERANCE


# ── Main function ──────────────────────────────────────────────────────

_MONEY = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)")
_SCORE = re.compile(r"(?:credit score (?:of |is )?|score of )(\d{3})|(\d{3})\s*(?:credit score|or above|\+)")


def _context_tier(context_text: str) -> tuple[int | None, float | None]:
    """Credit score / balance stated in the question or reply (general questions only)."""
    score = balance = None
    m = _SCORE.search(context_text or "")
    if m:
        score = int(m.group(1) or m.group(2))
    amounts = [float(a.replace(",", "")) for a in _MONEY.findall(context_text or "")]
    if amounts:
        balance = max(amounts)
    return score, balance


def verify_claim(claim: dict, customer_id: str, context_text: str = "") -> dict:
    """
    Deterministically verify one claim from extract_and_match().

    Returns:
        action          "PASS" | "CORRECT" | "FALLBACK"
        correct_value   str | None  — set when action is CORRECT
        correct_basis   str | None  — APR/APY/fee-type when action is CORRECT
        reason          human-readable explanation
        references      list of golden_dataset rows actually consulted to reach this verdict
    """
    refs: list[dict] = []

    def _ref(file: str, row: dict, why: str) -> None:
        refs.append({"file": f"golden_dataset/{file}", "row": dict(row), "why": why})

    def _fallback(reason: str) -> dict:
        return {"action": "FALLBACK", "correct_value": None, "correct_basis": None, "reason": reason, "references": list(refs)}

    def _correct(reason: str, correct_value: str, correct_basis: str | None = None) -> dict:
        return {"action": "CORRECT", "correct_value": correct_value, "correct_basis": correct_basis, "reason": reason, "references": list(refs)}

    def _pass(reason: str) -> dict:
        return {"action": "PASS", "correct_value": None, "correct_basis": None, "reason": reason, "references": list(refs)}

    # ── Rule 0: Ambiguous reference (e.g. "my loan" with multiple loans) → FALLBACK
    if claim.get("is_ambiguous_reference"):
        return _fallback(
            "Ambiguous product reference — customer holds multiple products of this type "
            "and the bot did not clarify which one was meant."
        )

    # ── Rule 0b: Product confusion (bot described a different product than asked) → CORRECT
    asked_id   = claim.get("asked_product_id")
    matched_id = claim.get("matched_product_id")
    if asked_id and matched_id and asked_id != matched_id:
        products  = _load_csv("products.csv")
        asked_p   = next((p for p in products if p["product_id"] == asked_id),   None)
        matched_p = next((p for p in products if p["product_id"] == matched_id), None)
        asked_name   = asked_p["product_name"]   if asked_p   else asked_id
        matched_name = matched_p["product_name"] if matched_p else matched_id
        if asked_p:
            _ref("products.csv", asked_p, "product the customer actually asked about")
        if matched_p:
            _ref("products.csv", matched_p, "product the bot's response actually described")
        return _correct(
            f"Bot described {matched_name} but customer asked about {asked_name}.",
            None,
        )

    # ── Rule 1: Low / missing product match → FALLBACK ─────────────────
    product_id = claim.get("matched_product_id")
    confidence = claim.get("match_confidence", "low")

    if not product_id or confidence == "low":
        return _fallback(
            f"Low match confidence or no product identified — cannot verify claim '{claim.get('claim_text', '')}'. "
            "Routing to human review."
        )

    # ── Load product info ──────────────────────────────────────────────
    products = _load_csv("products.csv")
    product  = next((p for p in products if p["product_id"] == product_id), None)
    if not product:
        return _fallback(f"Product '{product_id}' not found in catalog.")
    _ref("products.csv", product, "product definition — rate_basis (APR/APY) for this claim")

    expected_basis = product["rate_basis"]  # APR or APY
    claimed_value  = float(claim["value"])
    claimed_basis  = claim.get("basis")
    claim_type     = claim.get("claim_type", "rate")

    # ── Rule 2: Rate-basis confusion (APR vs APY) ──────────────────────
    if claim_type == "rate" and claimed_basis and claimed_basis != expected_basis:
        return _correct(
            f"Rate basis error: bot said {claimed_basis} but {product['product_name']} uses {expected_basis}.",
            f"{claimed_value}%",
            expected_basis,
        )

    # ── Load customer and account rows ─────────────────────────────────
    customer_row = None
    account_row  = None

    if customer_id:
        customers    = _load_csv("customers.csv")
        customer_row = next((c for c in customers if c["customer_id"] == customer_id), None)
        if customer_row:
            _ref("customers.csv", customer_row, "customer credit score, used to resolve pricing tier")

        accounts     = _load_csv("accounts.csv")
        acct_matches = [
            a for a in accounts
            if a["customer_id"] == customer_id and a["product_id"] == product_id
        ]
        if acct_matches:
            account_row = next(
                (a for a in acct_matches if a["status"] == "active"),
                acct_matches[0],
            )
            _ref("accounts.csv", account_row, "customer's account — status and locked-in rate")
            # Closed account
            if account_row["status"] == "closed":
                return _correct(
                    f"Account {account_row['account_id']} is closed. Quoting a rate for a closed account.",
                    None,
                )

    # ── Rule 3: Account-specific question → check locked-in rate ───────
    is_account_specific = claim.get("is_account_specific", False)

    if is_account_specific and account_row:
        locked = account_row["rate_locked_in"]
        if claim_type == "rate" and _rate_ok(claimed_value, locked):
            return _pass(
                f"Matches customer's locked-in rate {locked} on account {account_row['account_id']}."
            )
        if claim_type == "rate":
            # Check if bot quoted today's catalog (not wrong, but note it)
            rules = _current_rules(product_id)
            credit_score = int(customer_row["credit_score"]) if customer_row else None
            balance      = float(account_row["current_balance"])
            rule         = _applicable_rule(rules, credit_score, balance)
            if rule and _rate_ok(claimed_value, rule["rate"]):
                _ref("pricing_rules.csv", rule, "today's catalog rate for this tier, acknowledged alongside locked-in rate")
                return _pass(
                    f"Bot quoted today's catalog rate ({rule['rate']}); "
                    f"customer's actual locked-in rate is {locked}. Both acknowledged."
                )
            return _correct(
                f"Bot quoted {claimed_value}% but customer's locked-in rate is {locked}.",
                locked,
                expected_basis,
            )

    # ── Rule 4: General / catalog question → check pricing_rules ───────
    rules = _current_rules(product_id)
    if not rules:
        return _fallback(f"No pricing rules found for {product_id}.")

    credit_score = int(customer_row["credit_score"]) if customer_row else None
    balance      = float(account_row["current_balance"]) if account_row else None

    # For general questions (no customer), accept any rate that exists in any tier
    if not customer_id:
        if claim_type == "rate":
            matching_tier = next((r for r in rules if _rate_ok(claimed_value, r["rate"])), None)
            if matching_tier:
                _ref("pricing_rules.csv", matching_tier, "matching pricing tier for this rate claim")
                return _pass(f"Rate {claimed_value}% matches tier '{matching_tier['tier_condition']}'.")
            # Pick the tier the customer described (balance / credit score) — never guess.
            ctx_score, ctx_balance = _context_tier(context_text)
            tier = _applicable_rule(rules, ctx_score, ctx_balance) if (ctx_score or ctx_balance) else None
            if not tier:
                return _fallback(
                    f"Rate {claimed_value}% not found in any current tier for {product['product_name']}, "
                    "and the tier could not be determined from the conversation.")
            _ref("pricing_rules.csv", tier, "current tier matching the balance/credit score in the conversation")
            return _correct(
                f"Rate {claimed_value}% not found in any current tier for {product['product_name']}. "
                f"Tier '{tier['tier_condition']}' pays {tier['rate']}.",
                tier["rate"], expected_basis,
            )
        if claim_type == "fee":
            matching_tier = next((r for r in rules if _fee_ok(claimed_value, r["fee"])), None)
            if matching_tier:
                _ref("pricing_rules.csv", matching_tier, "matching pricing tier for this fee claim")
                return _pass(f"Fee ${claimed_value} matches tier '{matching_tier['tier_condition']}'.")
            ctx_score, ctx_balance = _context_tier(context_text)
            tier = _applicable_rule(rules, ctx_score, ctx_balance) if (ctx_score or ctx_balance) else None
            if not tier:
                return _fallback(f"Fee ${claimed_value} not found in any current tier, and the tier "
                                 "could not be determined from the conversation.")
            _ref("pricing_rules.csv", tier, "current tier matching the balance/credit score in the conversation")
            return _correct(
                f"Fee ${claimed_value} not found in any current tier. Tier '{tier['tier_condition']}' charges {tier['fee']}.",
                tier["fee"], tier.get("fee_type"),
            )

    # Customer known — use their tier
    rule = _applicable_rule(rules, credit_score, balance)
    if not rule:
        return _fallback("Could not determine an applicable pricing tier for this customer.")

    if claim_type == "rate":
        if _rate_ok(claimed_value, rule["rate"]):
            _ref("pricing_rules.csv", rule, "pricing tier applicable to this customer's credit score/balance")
            return _pass(f"Rate matches tier '{rule['tier_condition']}' ({rule['rate']}).")
        # Wrong tier?
        other = next((r for r in rules if _rate_ok(claimed_value, r["rate"])), None)
        if other:
            _ref("pricing_rules.csv", other, "tier the bot's quoted rate actually belongs to")
            _ref("pricing_rules.csv", rule, "tier this customer actually qualifies for")
            return _correct(
                f"Rate {claimed_value}% belongs to tier '{other['tier_condition']}' "
                f"but customer qualifies for '{rule['tier_condition']}' ({rule['rate']}).",
                rule["rate"], expected_basis,
            )
        _ref("pricing_rules.csv", rule, "pricing tier applicable to this customer's credit score/balance")
        return _correct(
            f"Rate {claimed_value}% not found in any current tier. Correct: {rule['rate']}.",
            rule["rate"], expected_basis,
        )

    if claim_type == "fee":
        _ref("pricing_rules.csv", rule, "pricing tier applicable to this customer's credit score/balance")
        if _fee_ok(claimed_value, rule["fee"]):
            return _pass(f"Fee matches tier '{rule['tier_condition']}' ({rule['fee']}).")
        return _correct(
            f"Fee ${claimed_value} does not match. Correct: {rule['fee']} ({rule['fee_type']}).",
            rule["fee"], rule["fee_type"],
        )

    return _fallback("Unrecognised claim type.")
