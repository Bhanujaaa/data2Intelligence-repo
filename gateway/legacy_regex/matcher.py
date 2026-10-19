"""
Step 2 — Product Matching
Given the customer question + bot response, identify which product from
golden_dataset/products.csv is being discussed.

Returns:
    {"product_id": ..., "product_name": ..., "rate_basis": ...}  — single match
    None                                                          — no product found (FALLBACK)
    {"ambiguous": True, "candidates": [...]}                      — multiple matches (FALLBACK)
"""

import csv
import os
import re

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PRODUCTS_CSV = os.path.join(_PROJECT_ROOT, "golden_dataset", "products.csv")


def _load_products() -> list[dict]:
    with open(_PRODUCTS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# Keywords that signal a product variant NOT in the catalog
_NON_CATALOG_QUALIFIERS = re.compile(
    r'\b(jumbo|money market|3.month|3 month|three.month|heloc|brokerage|ira|roth|student|business)\b',
    re.IGNORECASE,
)


def _tokenize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", text.lower())


def match_product(customer_question: str, bot_response: str) -> dict | None:
    # If question or response mentions a product variant not in the catalog → no match
    combined_raw = f"{customer_question} {bot_response}"
    if _NON_CATALOG_QUALIFIERS.search(combined_raw):
        return None

    """
    Score every product against the combined conversation text.
    Returns the best match, an ambiguity signal, or None.
    """
    products = _load_products()
    combined = _tokenize(f"{customer_question} {bot_response}")

    scores: list[tuple[int, dict]] = []

    for product in products:
        name_tokens = _tokenize(product["product_name"]).split()
        # Score = number of name tokens found in the combined text
        score = sum(1 for tok in name_tokens if tok in combined and len(tok) > 2)

        # Bonus: exact full name match
        if _tokenize(product["product_name"]) in combined:
            score += len(name_tokens)

        if score > 0:
            scores.append((score, product))

    if not scores:
        return None

    scores.sort(key=lambda x: x[0], reverse=True)
    best_score = scores[0][0]

    # Ambiguous: two products tie at the top with a meaningful score
    top_matches = [p for s, p in scores if s == best_score]
    if len(top_matches) > 1 and best_score >= 2:
        return {
            "ambiguous": True,
            "candidates": [
                {"product_id": p["product_id"], "product_name": p["product_name"]}
                for p in top_matches
            ],
        }

    best = scores[0][1]
    return {
        "product_id":   best["product_id"],
        "product_name": best["product_name"],
        "category":     best["category"],
        "rate_basis":   best["rate_basis"],
        "ambiguous":    False,
    }
