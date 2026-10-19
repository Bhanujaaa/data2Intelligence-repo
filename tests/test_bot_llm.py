"""The chatbot always calls the LLM — no scripted answers. Groq is mocked."""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["GATEWAY_WRITE_DIR"] = tempfile.mkdtemp()
os.environ["BOT_WRITE_DIR"] = tempfile.mkdtemp()
os.environ["GROQ_API_KEY"] = "test-key"

from fastapi.testclient import TestClient     # noqa: E402

from bot import bot                            # noqa: E402
from bot.api import app                        # noqa: E402


class FakeGroq:
    calls = []

    def __init__(self, api_key):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, **kw):
        FakeGroq.calls.append(messages)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content="You'd qualify for our best Personal Loan rate of 6.99% APR."))])


def test_every_answer_comes_from_the_llm_without_names_or_rates():
    FakeGroq.calls.clear()
    with mock.patch("groq.Groq", FakeGroq):
        r = bot.get_bot_response("CUST003", "What APR would I get on a Personal Loan?")
    assert r["bot_response"].startswith("You'd qualify")
    system = FakeGroq.calls[0][0]["content"]
    assert "Sofia" not in system and "Reyes" not in system        # no customer name
    assert "6.99%" not in system and "tier" not in system.lower()  # no rate sheet (own account rates only)
    assert "credit score 680" in system


def test_chat_endpoint_masks_pii_and_uses_the_llm():
    FakeGroq.calls.clear()
    with mock.patch("groq.Groq", FakeGroq):
        res = TestClient(app).post("/chat", json={
            "customer_id": "", "customer_question": "Card 4111 1111 1111 1111 — personal loan APR?"})
    assert res.status_code == 200 and res.json()["live"] is True
    assert "4111" not in FakeGroq.calls[0][1]["content"]


def test_no_scripted_answers_are_served():
    rows = TestClient(app).get("/sample-questions").json()
    assert rows and all("bot_response" not in r for r in rows)
    assert not (ROOT / "bot" / "data" / "scripted_responses.csv").exists()


def test_missing_key_is_an_error_not_a_script():
    with mock.patch.dict(os.environ, {"GROQ_API_KEY": ""}):
        res = TestClient(app).post("/chat", json={"customer_id": "", "customer_question": "rate?"})
    assert res.status_code == 500
