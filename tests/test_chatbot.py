"""Chatbot and API tests. Groq is mocked, so no API key is needed."""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["GATEWAY_WRITE_DIR"] = tempfile.mkdtemp()
os.environ["CHATBOT_WRITE_DIR"] = tempfile.mkdtemp()
os.environ["GROQ_API_KEY"] = "test-key"

from fastapi.testclient import TestClient     # noqa: E402

from api.main import app                       # noqa: E402
from chatbot import assistant                  # noqa: E402


class StubGroq:
    calls = []

    def __init__(self, api_key):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, **kw):
        StubGroq.calls.append(messages)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content="You'd qualify for our best Personal Loan rate of 6.99% APR."))])


def test_prompt_has_no_customer_name_or_rate_sheet():
    StubGroq.calls.clear()
    with mock.patch("groq.Groq", StubGroq):
        r = assistant.generate_answer("CUST003", "What APR would I get on a Personal Loan?")
    assert r["bot_response"].startswith("You'd qualify")
    system = StubGroq.calls[0][0]["content"]
    assert "Sofia" not in system and "Reyes" not in system        # no customer name
    assert "6.99%" not in system and "tier" not in system.lower()  # no rate sheet (own account rates only)
    assert "credit score 680" in system


def test_chat_endpoint_masks_pii_and_uses_the_llm():
    StubGroq.calls.clear()
    with mock.patch("groq.Groq", StubGroq):
        res = TestClient(app).post("/chat", json={
            "customer_id": "", "customer_question": "Card 4111 1111 1111 1111 — personal loan APR?"})
    assert res.status_code == 200 and res.json()["live"] is True
    assert "4111" not in StubGroq.calls[0][1]["content"]


def test_sample_questions_contain_questions_only():
    rows = TestClient(app).get("/sample-questions").json()
    assert rows and all("bot_response" not in r for r in rows)


def test_missing_key_returns_500():
    with mock.patch.dict(os.environ, {"GROQ_API_KEY": ""}):
        res = TestClient(app).post("/chat", json={"customer_id": "", "customer_question": "rate?"})
    assert res.status_code == 500
