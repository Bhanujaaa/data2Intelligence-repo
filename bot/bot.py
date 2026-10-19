"""
FirstVault chatbot — every answer comes from a live LLM (Groq).
===============================================================
There are no scripted answers. The bot is deliberately an ordinary chatbot:
it knows the product names and the customer's own accounts, but it does NOT
have the current rate sheet. When it quotes a rate or fee it may be right,
stale or invented — which is exactly what the gateway is there to catch.

The gateway is bot-agnostic: it only ever sees the bot's text.
"""

import csv
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GOLDEN_DIR   = os.path.join(_PROJECT_ROOT, "golden_dataset")


def _load_csv(filename: str) -> list[dict]:
    with open(os.path.join(_GOLDEN_DIR, filename), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _product_names() -> str:
    """Product names and rate basis only — no rates, no fees."""
    return "\n".join(
        f"- {p['product_name']} ({p['category']}, quoted as {p['rate_basis']})"
        for p in _load_csv("products.csv")
    )


def _customer_profile(customer_id: str) -> str:
    """What a real bank chatbot would know about a signed-in customer."""
    if not customer_id:
        return "The customer is not signed in."
    cust = next((c for c in _load_csv("customers.csv") if c["customer_id"] == customer_id), None)
    if not cust:
        return "The customer is not signed in."
    names = {p["product_id"]: p["product_name"] for p in _load_csv("products.csv")}
    accounts = [a for a in _load_csv("accounts.csv") if a["customer_id"] == customer_id]
    # No name or other identifiers are sent to the LLM — only what's needed to answer.
    lines = [f"Signed-in customer (credit score {cust['credit_score']}). Their accounts:"]
    for a in accounts:
        lines.append(f"- {names.get(a['product_id'], a['product_id'])}: rate {a['rate_locked_in']}, "
                     f"balance ${float(a['current_balance']):,.2f}, status {a['status']}")
    return "\n".join(lines)


_SYSTEM_PROMPT = """You are FirstVault Bank's customer-service chatbot.
Answer in 1-2 short sentences. When the customer asks about a rate or fee,
state a specific figure. You do not have the current rate sheet.

FirstVault products:
{products}

{profile}"""


def get_bot_response(customer_id: str, customer_question: str) -> dict:
    """Ask the live LLM. Returns {"bot_response": str, "model": str}.

    Raises EnvironmentError / ImportError / provider errors — the API turns
    those into HTTP errors; nothing falls back to a script.
    """
    try:
        from groq import Groq
    except ImportError:
        raise ImportError("Run: pip install groq")

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError("GROQ_API_KEY is not set in the environment.")
    model_id = os.environ.get("GROQ_BOT_MODEL") or os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")

    system = _SYSTEM_PROMPT.format(products=_product_names(), profile=_customer_profile(customer_id))
    response = Groq(api_key=api_key).chat.completions.create(
        model=model_id,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": customer_question}],
        max_tokens=1000,
        temperature=0.7,
    )
    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise RuntimeError("The LLM returned an empty answer.")
    return {"bot_response": text, "model": model_id}


# Backwards-compatible name used by older callers.
def get_live_bot_response(customer_question: str, customer_id: str = "") -> str:
    return get_bot_response(customer_id, customer_question)["bot_response"]
