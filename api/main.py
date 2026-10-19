"""
FastAPI backend — the LLM chatbot (/chat) and the verification gateway (/verify) for the React UI.
Run: uvicorn api.main:app --reload  (from project root)
"""

import csv
import json
import os
import sys
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from chatbot.assistant import generate_answer

# Gateway lives one level up; make it importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gateway.gateway import run_gateway

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GOLDEN_DIR   = os.path.join(_PROJECT_ROOT, "golden_dataset")
_CHATBOT_DIR  = os.path.join(_PROJECT_ROOT, "chatbot")
_OUTPUT_DIR   = os.path.join(os.environ.get("CHATBOT_WRITE_DIR", _CHATBOT_DIR), "output")
os.makedirs(_OUTPUT_DIR, exist_ok=True)

def _load_csv(directory: str, filename: str) -> list[dict]:
    with open(os.path.join(directory, filename), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def _write_response(payload: dict) -> None:
    payload["timestamp"] = datetime.now(timezone.utc).isoformat()
    with open(os.path.join(_OUTPUT_DIR, "last_response.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

app = FastAPI(title="Data2Intelligence API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    customer_id: str
    customer_question: str


class VerifyRequest(BaseModel):
    customer_id: str
    customer_question: str
    bot_response: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/customers")
def list_customers():
    return _load_csv(_GOLDEN_DIR, "customers.csv")


@app.get("/sample-questions")
def sample_questions():
    """Example questions for the UI (questions only)."""
    return _load_csv(_GOLDEN_DIR, "sample_questions.csv")


def _ask_llm(req: "ChatRequest") -> dict:
    # Mask PII before the question goes to the LLM (Groq)
    from gateway.pii import mask_pii
    masked_question, _ = mask_pii(req.customer_question)
    try:
        result = generate_answer(req.customer_id, masked_question)
    except (EnvironmentError, ImportError) as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")
    payload = {
        "customer_id": req.customer_id,
        "customer_question": masked_question,
        "bot_response": result["bot_response"],
        "model": result["model"],
        "live": True,
    }
    _write_response(payload)
    return payload


@app.post("/chat")
def chat(req: ChatRequest):
    """Generate the chatbot's answer with the LLM."""
    return _ask_llm(req)


@app.post("/chat/live")
def chat_live(req: ChatRequest):
    """Alias of /chat."""
    return _ask_llm(req)


@app.post("/verify")
def verify(req: VerifyRequest):
    """Run the gateway on a chatbot answer and return the verified result."""
    entry = {
        "customer_id":       req.customer_id,
        "customer_question": req.customer_question,
        "bot_response":      req.bot_response,
    }
    result = run_gateway(entry)
    return {
        "action":            result["action"],
        "original_response": req.bot_response,
        "final_response":    result["final_response"],
        "claims_extracted":  len(result["claims_extracted"] or []),
        "verdicts": [
            {
                "claim_text": v["claim"]["claim_text"] if v["claim"] else None,
                "action":     v["verdict"]["action"],
                "reason":     v["verdict"]["reason"],
                "correct_value": v["verdict"].get("correct_value"),
            }
            for v in result["verdicts"]
        ],
        "reliability":  result["reliability"],
        "references":   result["references"],
        "lineage":      result["lineage"],
        "human_review": result["human_review"],
        "trust_signals": result["trust_signals"],
        "pii_masked":   result["pii_masked"],
    }


@app.get("/health")
def health():
    return {"status": "ok"}
