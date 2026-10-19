"""
Step 1+2 — LLM-powered Extraction & Matching
=============================================
One LLM call (Groq) that:
  - Extracts every rate/fee claim from the bot response (handles natural phrasing
    that regex would miss — "just over nine percent", "around 7%", etc.)
  - Matches each claim to the correct product and tier from the catalog
  - Resolves ambiguous references ("my loan", "the card") using the customer's
    actual account context

Returns a list of structured claim dicts. If the LLM call fails for any reason,
returns [] so the gateway falls back to FALLBACK rather than silently passing.
"""

import csv
import json
import os
import re
import sys

from dotenv import load_dotenv

# Load .env from project root
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

_GOLDEN_DIR  = os.path.join(_PROJECT_ROOT, "golden_dataset")
_GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
_GROQ_MODEL   = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")


# ── Data loaders ───────────────────────────────────────────────────────

def _load_csv(filename: str) -> list[dict]:
    path = os.path.join(_GOLDEN_DIR, filename)
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _customer_context(customer_id: str) -> str:
    """Build a compact text block describing what products the customer actually holds."""
    if not customer_id:
        return "No specific customer — general product enquiry."

    customers = _load_csv("customers.csv")
    cust = next((c for c in customers if c["customer_id"] == customer_id), None)
    if not cust:
        return f"Customer {customer_id} not found."

    accounts = _load_csv("accounts.csv")
    products = _load_csv("products.csv")
    prod_map = {p["product_id"]: p["product_name"] for p in products}

    held = [
        a for a in accounts
        if a["customer_id"] == customer_id and a["status"] == "active"
    ]

    lines = [
        # No name is sent to the LLM — the customer id and tier inputs are enough.
        f"Customer {customer_id} "
        f"(credit score: {cust['credit_score']}, joined: {cust['join_date']})",
        "Active accounts:"
    ]
    for a in held:
        lines.append(
            f"  - {prod_map.get(a['product_id'], a['product_id'])} "
            f"| locked-in rate: {a['rate_locked_in']} "
            f"| balance: ${float(a['current_balance']):,.2f}"
        )
    if not held:
        lines.append("  (no active accounts)")

    return "\n".join(lines)


def _product_catalog_text() -> str:
    """Compact product catalog for the LLM prompt."""
    products = _load_csv("products.csv")
    lines = ["Product catalog:"]
    for p in products:
        lines.append(f"  {p['product_id']} | {p['product_name']} | {p['category']} | {p['rate_basis']}")
    return "\n".join(lines)


# ── Prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a financial compliance assistant at a bank.
Your job is to extract rate and fee claims from a customer service bot's response and match each claim to the correct bank product.

Return ONLY a valid JSON array. No markdown, no explanation, no preamble — just the JSON.

Each element in the array must have exactly these fields:
{
  "claim_text": "the exact text from the bot response that contains the claim",
  "claim_type": "rate" or "fee",
  "value": <numeric value as a float, e.g. 6.99 for 6.99% or 50 for $50>,
  "basis": "APR" or "APY" or null,
  "matched_product_id": "the product_id from the catalog that the BOT RESPONSE is describing, or null if unknown",
  "asked_product_id": "the product_id the CUSTOMER was asking about — may differ from matched_product_id if bot answered about the wrong product, or null if unclear",
  "match_confidence": "high" or "low",
  "match_reasoning": "one sentence explaining how you matched the product",
  "is_account_specific": <true if the question is about the customer's own account, false for a general product question>,
  "is_ambiguous_reference": <true if the customer used a vague reference like 'my loan', 'my card', 'my account' AND the customer holds multiple active products of that same type — so it's genuinely unclear which product they meant>
}

Rules:
- Extract ALL rate (%) and fee ($) claims. Include 0% intro rates and $0 fees.
- Do NOT extract dollar amounts that are balance thresholds (e.g. "$10,000 deposit") — only rates and fees.
- If no financial claims exist in the response, return an empty array: []
- If you cannot confidently match a claim to a product, set matched_product_id to null and match_confidence to "low".
- If the bot answered about a DIFFERENT product than the one the customer asked about, set asked_product_id to the customer's product and matched_product_id to what the bot described.
- Set is_ambiguous_reference to true ONLY when: (a) the customer used a vague possessive like 'my loan', 'my savings', 'my card', AND (b) the customer's account list shows multiple active products of that type.
- When the rate basis in the response does not match the product's typical basis (e.g. bot said APY for a mortgage which uses APR), still set match_confidence to "high" — the basis error will be caught by the verifier.
"""


def _user_message(customer_question: str, bot_response: str, customer_id: str) -> str:
    return f"""## Customer question
{customer_question}

## Bot response (extract claims from this)
{bot_response}

## Customer context
{_customer_context(customer_id)}

## {_product_catalog_text()}

Extract all rate/fee claims from the bot response and return the JSON array."""


# ── JSON extraction ────────────────────────────────────────────────────

def _parse_llm_json(raw: str) -> list[dict]:
    """
    Robustly extract a JSON array from LLM output.
    Handles: markdown fences, <think>...</think> reasoning blocks (Qwen), preamble.
    """
    # Strip <think>...</think> blocks (Qwen reasoning model — may be closed or unclosed)
    if "<think>" in raw:
        if "</think>" in raw:
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        else:
            # Thinking block never closed — model ran out of tokens mid-reasoning
            # Nothing useful follows; return empty to signal "no claims found"
            return []
    # Strip markdown code fences
    raw = re.sub(r"```(?:json)?", "", raw).strip()

    # Try direct parse first
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Find the outermost [...] block
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    return []


# ── Main function ──────────────────────────────────────────────────────

def extract_and_match(
    bot_response:      str,
    customer_question: str,
    customer_id:       str = "",
) -> list[dict] | None:
    """
    Call the Groq LLM to extract rate/fee claims and match each to a product.

    Returns a list of claim dicts (possibly empty).
    On any error, returns [] — the gateway will route to FALLBACK.
    """
    if not _GROQ_API_KEY:
        print("WARNING: GROQ_API_KEY not set — skipping LLM call", file=sys.stderr)
        return None

    try:
        from groq import Groq
    except ImportError:
        print("WARNING: groq package not installed. Run: pip install groq", file=sys.stderr)
        return None

    try:
        import time
        client = Groq(api_key=_GROQ_API_KEY)

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": _user_message(customer_question, bot_response, customer_id)},
        ]

        # Retry up to 4 times on rate-limit errors
        response = None
        for attempt in range(4):
            try:
                response = client.chat.completions.create(
                    model=_GROQ_MODEL,
                    messages=messages,
                    max_tokens=4000,
                    temperature=0.0,
                )
                break
            except Exception as e:
                err_str = str(e)
                if "rate_limit_exceeded" in err_str or "429" in err_str:
                    import re as _re
                    wait_match = _re.search(r"try again in ([\d.]+)s", err_str)
                    wait = float(wait_match.group(1)) + 0.5 if wait_match else 2 ** attempt + 1
                    print(f"\n  [rate limit] waiting {wait:.1f}s...", end=" ", flush=True)
                    time.sleep(wait)
                    if attempt == 3:
                        raise
                else:
                    raise

        if response is None:
            # All retries exhausted — return None to signal LLM failure (not "no claims")
            return None

        raw_text = response.choices[0].message.content.strip()
        claims   = _parse_llm_json(raw_text)

        # Validate each claim has required fields; drop malformed ones
        valid = []
        for c in claims:
            if not isinstance(c, dict):
                continue
            if "claim_type" not in c or "value" not in c:
                continue
            try:
                c["value"] = float(c["value"])
            except (TypeError, ValueError):
                continue
            c.setdefault("basis", None)
            c.setdefault("matched_product_id", None)
            c.setdefault("asked_product_id", None)
            c.setdefault("match_confidence", "low")
            c.setdefault("match_reasoning", "")
            c.setdefault("is_account_specific", False)
            c.setdefault("is_ambiguous_reference", False)
            c.setdefault("claim_text", "")
            valid.append(c)

        return valid

    except Exception as e:
        print(f"WARNING: LLM extraction failed ({e}) — returning None (FALLBACK)", file=sys.stderr)
        return None
