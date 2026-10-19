"""
Offline tests for the gateway — no Groq key, no AWS.
The LLM step is replaced by the claims a correct extraction would return,
so these tests check the deterministic part: verify rules, corrections,
trust signals, PII masking and fail-closed behaviour.

Run from the project root:  python -m pytest -q
"""
import csv
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["GATEWAY_WRITE_DIR"] = tempfile.mkdtemp()
os.environ.pop("AUDIT_TABLE", None)

from gateway import gateway, trust_signals          # noqa: E402
from gateway.pii import mask_pii                     # noqa: E402

CASES = {r["id"]: r for r in csv.DictReader(open(ROOT / "tests" / "fixtures" / "gateway_test_cases.csv"))}


def claim(text, value, product, basis=None, ctype="rate", asked=None, account=False, ambiguous=False, conf="high"):
    return {"claim_text": text, "claim_type": ctype, "value": value, "basis": basis,
            "matched_product_id": product, "asked_product_id": asked or product,
            "match_confidence": conf, "match_reasoning": "", "is_account_specific": account,
            "is_ambiguous_reference": ambiguous}


# What a correct LLM extraction returns for each case (the deterministic part is under test).
CLAIMS = {
    "TC001": [claim("4.20% APY", 4.20, "SAV002", "APY")],
    "TC002": [claim("6.99% APR", 6.99, "LOAN001", "APR")],
    "TC004": [claim("6.99% APR", 6.99, "LOAN001", "APR")],
    "TC005": [claim("9.99% APR", 9.99, "AUTO001", "APR")],
    "TC009": [claim("4.85% APR", 4.85, "CD001", "APR")],
    "TC011": [claim("4.50% APY", 4.50, "SAV002", "APY")],
    "TC012": [claim("4.50% APY", 4.50, "SAV002", "APY")],
    "TC013": [claim("3.10% APY", 3.10, None, "APY", conf="low")],
    "TC017": [claim("29.99% APR", 29.99, "LOAN001", "APR", account=True, ambiguous=True)],
    "TC019": [claim("14.99% APR", 14.99, "LOAN001", "APR"), claim("$50", 50, "LOAN001", None, "fee")],
    "TC021": [],
    "TC023": [claim("0.50% APY", 0.50, "SAV001", "APY", account=True)],
    "TC026": [claim("3.80% APY", 3.80, "SAV002", "APY", account=True)],
    "TC028": [claim("20.49%", 20.49, "CARD002", None, account=True)],
}


def run(case_id, claims=None):
    c = CASES[case_id]
    entry = {"customer_id": c["customer_id"], "customer_question": c["customer_question"],
             "bot_response": c["bot_response"]}
    with mock.patch.object(gateway, "extract_and_match",
                           return_value=CLAIMS[case_id] if claims is None else claims):
        return gateway.run_gateway(entry)


def test_every_fixture_case_gets_its_expected_action():
    for cid in CLAIMS:
        r = run(cid)
        assert r["action"] == CASES[cid]["expected_gateway_action"], (cid, r["action"], r["verdicts"])


def test_wrong_tier_is_corrected_to_the_customers_tier():
    r = run("TC004")
    assert "14.99%" in r["final_response"]


def test_stale_rate_is_corrected_to_the_right_tier_not_the_first_row():
    # Bug in the hackathon run: 4.50% was "corrected" to 3.80%. The right value is 4.20%.
    for cid in ("TC011", "TC012"):
        r = run(cid)
        assert "4.20%" in r["final_response"] and "3.80%" not in r["final_response"], r["final_response"]


def test_every_pass_or_correct_cites_golden_dataset_rows():
    for cid in ("TC001", "TC004", "TC011", "TC023"):
        r = run(cid)
        assert r["references"] and all(ref["file"].startswith("golden_dataset/") for ref in r["references"])
        assert all(c["provenance"]["score"] == 1.0 for c in r["trust_signals"]["claims"])


def test_conflicting_branch_faq_is_surfaced_and_outranked():
    r = run("TC004")                               # bot said 6.99%, branch FAQ also says 6.99%
    conflicts = r["trust_signals"]["conflicts"]
    assert conflicts and conflicts[0]["file"] == "secondary_sources/branch_faq.csv"
    assert conflicts[0]["bot_repeated_this"] is True
    r = run("TC001")                               # 4.20%: marketing page agrees, FAQ (4.50%) does not
    agree = r["trust_signals"]["claims"][0]["agreement"]
    assert 0 < agree["score"] < 1 and agree["conflicts"][0]["value"] == "4.50"


def test_llm_failure_fails_closed():
    r = run("TC001", claims=None)
    with mock.patch.object(gateway, "extract_and_match", return_value=None):
        r = gateway.run_gateway({"customer_id": "", "customer_question": "rate?", "bot_response": "6.99%"})
    assert r["action"] == "FALLBACK"


def test_expired_pricing_rule_triggers_freshness_gate():
    r = run("TC001")
    verdicts = r["verdicts"]
    t = trust_signals.evaluate(verdicts, today=date(2027, 12, 31))
    assert t["freshness_gate"] is True
    assert trust_signals.evaluate(verdicts, today=date(2026, 10, 19))["freshness_gate"] is False


def test_pii_is_masked_before_the_llm_and_the_audit_log():
    seen = {}
    def spy(bot_response, customer_question, customer_id=""):
        seen["q"] = customer_question
        return CLAIMS["TC001"]
    with mock.patch.object(gateway, "extract_and_match", side_effect=spy):
        r = gateway.run_gateway({"customer_id": "", "bot_response": CASES["TC001"]["bot_response"],
                                 "customer_question": "My card 4111 1111 1111 1111, email a@b.com. " +
                                                      CASES["TC001"]["customer_question"]})
    assert "4111" not in seen["q"] and "a@b.com" not in seen["q"]
    assert set(r["pii_masked"]) == {"CARD_NUMBER", "EMAIL"}
    log = Path(gateway._AUDIT_LOG).read_text()
    assert "4111" not in log


def test_pii_masking_leaves_rates_and_amounts_alone():
    text, found = mask_pii("Balances of $10,000 earn 4.20% APY; fee $50.")
    assert text == "Balances of $10,000 earn 4.20% APY; fee $50." and found == []
