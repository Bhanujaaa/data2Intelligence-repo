"""
Terminal demo: ask the chatbot, then verify its answer with the gateway.
=======================================================================
The verdict (PASS / CORRECT / FALLBACK) depends on what the model says.

Usage:
    python gateway/demo.py --customer CUST003 "What APR would I get on a Personal Loan?"
    python gateway/demo.py "What APY does the High-Yield Savings offer for balances over $10,000?"
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chatbot.assistant import generate_answer  # noqa: E402
from gateway.gateway import run_gateway        # noqa: E402
from gateway.pii import mask_pii               # noqa: E402

COLOR = {"PASS": "\033[92m", "CORRECT": "\033[93m", "FALLBACK": "\033[91m"}
RESET, BOLD = "\033[0m", "\033[1m"


def main():
    p = argparse.ArgumentParser(description="Live gateway demo")
    p.add_argument("question")
    p.add_argument("--customer", default="", help="e.g. CUST003")
    a = p.parse_args()

    question, _ = mask_pii(a.question)
    answer = generate_answer(a.customer, question)["bot_response"]
    print(f"\n{BOLD}Question{RESET} : {question}")
    print(f"{BOLD}Chatbot{RESET}  : {answer}\n")

    r = run_gateway({"customer_id": a.customer, "customer_question": question, "bot_response": answer})
    act = r["action"]
    print(f"{BOLD}Gateway{RESET}  : {COLOR.get(act, '')}{act}{RESET}")
    for v in r["verdicts"]:
        c = v["claim"]
        print(f"  - {c['claim_text'] if c else '(no claim)'}: {v['verdict']['action']} — {v['verdict']['reason'][:90]}")
    print(f"{BOLD}Customer sees{RESET}: {r['final_response']}")
    print(f"{BOLD}Reliability{RESET}  : {r['reliability']['score']}/100")
    for ref in r["references"]:
        print(f"  ref: {ref['file']} {ref['row'].get('rule_id') or ref['row'].get('account_id') or ref['row'].get('product_id')} — {ref['why']}")
    for x in r["trust_signals"]["conflicts"]:
        print(f"  outranked: {x['file']} {x['row_id']} said {x['value']} (as of {x['as_of']})")


if __name__ == "__main__":
    main()
