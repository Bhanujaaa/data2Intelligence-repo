"""
Ask the chatbot every sample question and save its answers.
============================================================
Feed the output to the gateway with:  python gateway/gateway.py --batch

Usage:
    python scripts/run_sample_questions.py               # all sample questions
    python scripts/run_sample_questions.py --delay 4     # seconds between calls (Groq free plan)
    python scripts/run_sample_questions.py --ask "What APR would I get on a Personal Loan?" --customer CUST003
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CHATBOT_DIR  = os.path.join(_PROJECT_ROOT, "chatbot")
_OUTPUT_DIR   = os.path.join(os.environ.get("CHATBOT_WRITE_DIR", _CHATBOT_DIR), "output")
_QUESTIONS    = os.path.join(_PROJECT_ROOT, "golden_dataset", "sample_questions.csv")
sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv                       # noqa: E402
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

from chatbot.assistant import generate_answer        # noqa: E402
from gateway.pii import mask_pii                     # noqa: E402


def run_all(delay: float):
    with open(_QUESTIONS, newline="", encoding="utf-8") as f:
        questions = list(csv.DictReader(f))
    records = []
    print(f"\nAsking the LLM chatbot {len(questions)} questions\n" + "-" * 80)
    for q in questions:
        question, _ = mask_pii(q["customer_question"])
        try:
            answer = generate_answer(q["customer_id"], question)["bot_response"]
        except Exception as e:                       # keep going; record the failure
            answer = f"[LLM error: {e}]"
        print(f"[{q['id']}] {q['customer_id'] or '(general)'}: {question}\n   -> {answer}\n")
        records.append({"id": q["id"], "customer_id": q["customer_id"],
                        "customer_question": question, "bot_response": answer})
        time.sleep(delay)
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    out = os.path.join(_OUTPUT_DIR, "responses.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now(timezone.utc).isoformat(),
                   "source": "llm", "responses": records}, f, indent=2)
    print(f"Saved {len(records)} answers -> {out}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Ask the LLM chatbot")
    p.add_argument("--ask", metavar="QUESTION", help="Ask one question")
    p.add_argument("--customer", default="", help="Customer id for --ask, e.g. CUST003")
    p.add_argument("--delay", type=float, default=3.0, help="Seconds between calls")
    a = p.parse_args()
    if a.ask:
        print(generate_answer(a.customer, mask_pii(a.ask)[0])["bot_response"])
    else:
        run_all(a.delay)
