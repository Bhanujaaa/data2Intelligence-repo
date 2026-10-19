"""
PII masking — runs before anything leaves the gateway (Groq call, logs, audit).
=============================================================================
Deterministic regex masking, no external service. Rates ("6.99%") and dollar
amounts are not touched; only identifiers that could point to a person.
"""

import re

_PATTERNS = [
    ("CARD_NUMBER", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("PAN",         re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
    ("AADHAAR",     re.compile(r"\b\d{4}[ -]\d{4}[ -]\d{4}\b")),
    ("SSN",         re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("EMAIL",       re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")),
    ("PHONE",       re.compile(r"(?<![\d$.])(?:\+\d{1,3}[ -]?)?(?:\(\d{3}\)[ -]?|\d{3}[ -])\d{3}[ -]\d{4}\b|(?<![\d$.])[6-9]\d{9}\b")),
]


def mask_pii(text: str) -> tuple[str, list[str]]:
    """Return (masked_text, [entity types found])."""
    found = []
    for name, rx in _PATTERNS:
        if text and rx.search(text):
            found.append(name)
            text = rx.sub("{" + name + "}", text)
    return text, found
