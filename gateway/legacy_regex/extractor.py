"""
Step 1 — Claim Extraction
Scan the bot response for any number that looks like a rate (%) or a fee ($).
Returns a list of structured claim dicts; empty list means nothing to verify.
"""

import re

# Matches: "6.99% APR", "4.20% APY", "0.00%", "22.99 percent"
_RATE_PATTERN = re.compile(
    r'(\d{1,2}(?:\.\d{1,2})?)\s*%\s*(APR|APY)?'
    r'|(\d{1,2}(?:\.\d{1,2})?)\s+percent\s*(APR|APY)?',
    re.IGNORECASE,
)

# Matches: "$50", "$95", "$0" — fee amounts
_FEE_PATTERN = re.compile(r'\$(\d+(?:,\d{3})*(?:\.\d{2})?)', re.IGNORECASE)

# Basis keywords that might appear without a % sign
_BASIS_KEYWORDS = re.compile(r'\b(APR|APY)\b', re.IGNORECASE)


def extract_claims(bot_response: str) -> list[dict]:
    """
    Return a list of claims found in bot_response.

    Each claim dict has:
        type        "rate" | "fee"
        raw         the original matched string
        value       numeric string, e.g. "6.99" or "50"
        basis       "APR" | "APY" | None   (rates only)
    """
    claims = []
    seen_values = set()

    for m in _RATE_PATTERN.finditer(bot_response):
        value = m.group(1) or m.group(3)
        basis_raw = m.group(2) or m.group(4) or ""
        basis = basis_raw.upper() if basis_raw else None

        # If no explicit basis in the match, look for one nearby (±40 chars)
        if not basis:
            start = max(0, m.start() - 40)
            end   = min(len(bot_response), m.end() + 40)
            ctx   = bot_response[start:end]
            kb    = _BASIS_KEYWORDS.search(ctx)
            if kb:
                basis = kb.group(1).upper()

        key = (value, basis)
        if key in seen_values:
            continue
        seen_values.add(key)

        claims.append({
            "type":  "rate",
            "raw":   m.group(0).strip(),
            "value": value,          # e.g. "6.99"
            "basis": basis,          # "APR" | "APY" | None
        })

    # Context words that signal a dollar amount is a balance threshold, not a fee
    _balance_ctx = re.compile(
        r'\b(balance|deposit|minimum|over|more than|at least|up to|exceed)\b',
        re.IGNORECASE,
    )

    for m in _FEE_PATTERN.finditer(bot_response):
        value = m.group(1).replace(",", "")
        numeric = float(value)

        # Skip large round dollar amounts that are clearly balance thresholds
        if numeric >= 1000:
            start = max(0, m.start() - 50)
            ctx   = bot_response[start:m.end() + 20]
            if _balance_ctx.search(ctx):
                continue

        key = ("fee", value)
        if key in seen_values:
            continue
        seen_values.add(key)

        claims.append({
            "type":  "fee",
            "raw":   m.group(0).strip(),
            "value": value,
            "basis": None,
        })

    return claims
