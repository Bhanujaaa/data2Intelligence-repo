"""
Gateway Orchestrator
====================
Reads chatbot/output/last_response.json, runs the full LLM + deterministic pipeline,
applies corrections, and writes:
  - gateway/output/gateway_result.json   (full audit payload)
  - gateway/logs/audit_log.csv           (one row per claim, append mode)

Pipeline:
  1. extract_and_match()  — LLM: what claims, which product/tier?
  2. verify_claim()       — deterministic: does the value match the rulebook?
  3. Apply corrections    — swap wrong numbers; replace whole response on FALLBACK
  4. Log                  — one CSV row per claim

Usage:
    python gateway/gateway.py               # verify last_response.json (default)
    python gateway/gateway.py --batch       # verify all rows in responses.json
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gateway.extract_and_match import extract_and_match, _GROQ_MODEL as _EXTRACTION_MODEL
from gateway.verify             import verify_claim
from gateway.pii                import mask_pii
from gateway.trust_signals      import evaluate as evaluate_trust

_PROJECT_ROOT    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GOLDEN_DIR      = os.path.join(_PROJECT_ROOT, "golden_dataset")
_LAST_RESPONSE   = os.path.join(_PROJECT_ROOT, "chatbot", "output", "last_response.json")
_BATCH_RESPONSES = os.path.join(_PROJECT_ROOT, "chatbot", "output", "responses.json")
# On AWS Lambda only /tmp is writable: set GATEWAY_WRITE_DIR=/tmp there.
_WRITE_ROOT      = os.environ.get("GATEWAY_WRITE_DIR", os.path.join(_PROJECT_ROOT, "gateway"))
_OUTPUT_DIR      = os.path.join(_WRITE_ROOT, "output")
_LOG_DIR         = os.path.join(_WRITE_ROOT, "logs")
_AUDIT_TABLE     = os.environ.get("AUDIT_TABLE", "")   # DynamoDB table (AWS); empty = CSV only
_AUDIT_LOG       = os.path.join(_LOG_DIR, "audit_log.csv")
_AUDIT_FIELDS    = [
    "timestamp", "customer_id", "original_response", "claim_text",
    "claim_type", "claim_value", "matched_product_id", "match_confidence",
    "action_taken", "correct_value", "final_response",
]

os.makedirs(_OUTPUT_DIR, exist_ok=True)
os.makedirs(_LOG_DIR,    exist_ok=True)

_FALLBACK_MESSAGE = (
    "I want to make sure I give you accurate information. "
    "Let me pull the current, verified number for you — "
    "please hold while I confirm the details."
)


# ── Correction helpers ─────────────────────────────────────────────────

def _apply_correction(response_text: str, claim_text: str, correct_value: str, correct_basis: str | None) -> str:
    """Swap the wrong claim text with the corrected value in the response."""
    if not claim_text or not correct_value:
        return response_text
    basis_str = f" {correct_basis}" if correct_basis else ""
    replacement = f"{correct_value}{basis_str}"
    return response_text.replace(claim_text, replacement, 1)


def _overall_action(verdicts: list[dict]) -> str:
    actions = {v["action"] for v in verdicts}
    if "FALLBACK" in actions: return "FALLBACK"
    if "CORRECT"  in actions: return "CORRECT"
    return "PASS"


# ── Reliability scoring ─────────────────────────────────────────────────

_BASE_SCORE_BY_ACTION = {"PASS": 95, "CORRECT": 80, "FALLBACK": 25}


def _reliability_score(claims: list[dict] | None, verdicts: list[dict]) -> dict:
    """
    Score how much the final output can be trusted, 0-100.
    Weakest-link scoring: the final response is only as reliable as its
    least-confident claim. Deductions apply when the extraction step itself
    (an LLM judgment call) had low confidence in the product/tier match.
    """
    if claims is None:
        return {
            "score": 0, "label": "no confidence",
            "reason": "LLM extraction call failed entirely — nothing could be verified.",
        }

    per_claim_scores = []
    for v in verdicts:
        claim   = v["claim"]
        verdict = v["verdict"]
        score = _BASE_SCORE_BY_ACTION.get(verdict["action"], 25)
        if claim and claim.get("match_confidence") == "low":
            score -= 20
        per_claim_scores.append(max(0, min(100, score)))

    score = min(per_claim_scores) if per_claim_scores else 90
    if score >= 85:
        label = "high confidence"
    elif score >= 60:
        label = "medium confidence"
    else:
        label = "low confidence"

    specific_reasons = sorted({v["verdict"]["reason"] for v in verdicts})
    if score >= 85:
        reason = "All claims matched the golden dataset with high extraction confidence."
    elif score >= 60:
        reason = "At least one claim required a deterministic correction or had low match confidence: " + "; ".join(specific_reasons)
    else:
        reason = "At least one claim could not be confidently matched or verified — routed to fallback/human review: " + "; ".join(specific_reasons)
    return {"score": score, "label": label, "reason": reason}


# ── Lineage (audit trace) ────────────────────────────────────────────────

def _build_lineage(
    claims:      list[dict] | None,
    verdicts:    list[dict],
    overall:     str,
    corrections: list[dict],
) -> list[dict]:
    """Ordered, human-readable trace of how the final result was reached."""
    lineage = [{
        "step": 1,
        "stage": "extraction",
        "component": "gateway/extract_and_match.py",
        "uses_llm": True,
        "model": f"Groq: {_EXTRACTION_MODEL}",
        "description": (
            "LLM extraction call failed." if claims is None else
            f"Extracted {len(claims)} claim(s) from the bot response." if claims else
            "No rate/fee claims found in the bot response."
        ),
    }]

    for i, v in enumerate(verdicts, start=1):
        claim, verdict = v["claim"], v["verdict"]
        lineage.append({
            "step": 1 + i,
            "stage": "verification",
            "component": "gateway/verify.py",
            "uses_llm": False,
            "claim_text": claim.get("claim_text") if claim else None,
            "action": verdict["action"],
            "reason": verdict["reason"],
            "references": verdict.get("references", []),
        })

    if corrections:
        lineage.append({
            "step": len(lineage) + 1,
            "stage": "correction",
            "component": "gateway/gateway.py:_apply_correction()",
            "uses_llm": False,
            "description": "Replaced the incorrect claim text in-place with the verified correct value.",
            "corrections": corrections,
        })

    if overall == "FALLBACK":
        lineage.append({
            "step": len(lineage) + 1,
            "stage": "fallback_override",
            "component": "gateway/gateway.py:run_gateway()",
            "uses_llm": False,
            "description": "Overall action is FALLBACK — the entire response was replaced with a safe templated message.",
        })

    return lineage


def _dedupe_references(verdicts: list[dict]) -> list[dict]:
    seen, out = set(), []
    for v in verdicts:
        for ref in v["verdict"].get("references", []):
            key = (ref["file"], json.dumps(ref["row"], sort_keys=True))
            if key not in seen:
                seen.add(key)
                out.append(ref)
    return out


# ── Human-review fallback aid ────────────────────────────────────────────
# When the deterministic pipeline can't confirm a response, none of the
# above (references/lineage) has anything concrete to show — verify.py
# never got a confirmed product to work with. This does a best-effort
# keyword search over golden_dataset as a HINT for the human reviewer.
# It is NEVER used to auto-correct or auto-pass a response — only surfaced
# alongside the FALLBACK verdict so a person has a starting point.

def _load_golden_csv(filename: str) -> list[dict]:
    with open(os.path.join(_GOLDEN_DIR, filename), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _keywords(text: str) -> set[str]:
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", text.lower()).split() if len(w) > 2}


def _keyword_search_products(customer_question: str, bot_response: str) -> list[dict]:
    """Best-effort, unconfirmed candidate products by name/category keyword overlap."""
    words = _keywords(f"{customer_question} {bot_response}")
    candidates = []
    for p in _load_golden_csv("products.csv"):
        name_words = _keywords(p["product_name"])
        overlap = sorted(name_words & words)
        category_hit = p["category"].lower() in words
        if overlap or category_hit:
            candidates.append({
                "file": "golden_dataset/products.csv",
                "row": p,
                "matched_keywords": overlap or [p["category"].lower()],
                "confirmed": False,
            })
    candidates.sort(key=lambda c: len(c["matched_keywords"]), reverse=True)
    return candidates


def _probable_route(candidates: list[dict], reasons: list[str]) -> str:
    if not candidates:
        return (
            "Keyword search against golden_dataset/products.csv found no candidate product either. "
            "This may be a product outside the catalog, or the question/response didn't share any "
            "product-name or category words with the catalog. A human should check whether this is "
            "a new/unlisted product before answering the customer."
        )
    names = ", ".join(f"{c['row']['product_name']} ({c['row']['product_id']})" for c in candidates)
    return (
        f"Automated verification could not confirm a product match ({'; '.join(reasons)}). "
        f"Keyword search suggests this likely concerns: {names} — unconfirmed, not used to auto-correct "
        f"the response. A human reviewer should check golden_dataset/pricing_rules.csv for the applicable "
        f"tier under the correct product before responding to the customer."
    )


def _human_review_block(overall: str, customer_question: str, bot_response: str, verdicts: list[dict]) -> dict:
    if overall != "FALLBACK":
        return {"required": False}

    reasons = sorted({v["verdict"]["reason"] for v in verdicts})
    candidates = _keyword_search_products(customer_question, bot_response)
    return {
        "required": True,
        "reasons": reasons,
        "candidate_matches": candidates,
        "probable_route": _probable_route(candidates, reasons),
        "note": "Automated verification could not confirm this response. Do not send it to the customer as-is — route to a human reviewer.",
    }


# ── Audit logger ───────────────────────────────────────────────────────

def _write_audit_row(
    customer_id:       str,
    original_response: str,
    claim:             dict | None,
    verdict:           dict,
    final_response:    str,
):
    row = {
        "timestamp":         datetime.now(timezone.utc).isoformat(),
        "customer_id":       customer_id,
        "original_response": original_response,
        "claim_text":        claim.get("claim_text", "") if claim else "",
        "claim_type":        claim.get("claim_type", "") if claim else "",
        "claim_value":       claim.get("value", "")      if claim else "",
        "matched_product_id":claim.get("matched_product_id", "") if claim else "",
        "match_confidence":  claim.get("match_confidence", "") if claim else "",
        "action_taken":      verdict["action"],
        "correct_value":     verdict.get("correct_value") or "",
        "final_response":    final_response,
    }
    file_exists = os.path.exists(_AUDIT_LOG)
    with open(_AUDIT_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_AUDIT_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
    if _AUDIT_TABLE:
        _write_audit_dynamodb(row)


def _write_audit_dynamodb(row: dict):
    """One item per claim in DynamoDB (free tier). Keys: customer_id + timestamp."""
    import boto3
    import uuid
    item = {k: {"S": str(v)} for k, v in row.items()}
    item["audit_id"] = {"S": str(uuid.uuid4())}
    boto3.client("dynamodb").put_item(TableName=_AUDIT_TABLE, Item=item)


# ── Core pipeline ──────────────────────────────────────────────────────

def run_gateway(entry: dict) -> dict:
    """Run the full pipeline on one bot response entry."""
    customer_id       = entry.get("customer_id", "")
    # PII is masked before the LLM call, the audit log and the API response.
    customer_question, pii_q = mask_pii(entry.get("customer_question", ""))
    bot_response,      pii_b = mask_pii(entry.get("bot_response", ""))
    pii_masked        = sorted(set(pii_q + pii_b))
    ts                = datetime.now(timezone.utc).isoformat()

    # ── Step 1+2: LLM extraction + matching ───────────────────────────
    print(f"  [LLM] extracting claims from response...", end=" ", flush=True)
    claims = extract_and_match(bot_response, customer_question, customer_id)
    claim_count = len(claims) if claims is not None else "LLM failed"
    print(f"{claim_count} claim(s) found")

    # ── Step 3: Deterministic verification ────────────────────────────
    verdicts       = []
    final_response = bot_response

    if claims is None:
        # LLM call failed entirely — hard FALLBACK
        verdict = {"action": "FALLBACK", "correct_value": None, "correct_basis": None,
                   "reason": "LLM extraction failed — cannot verify response. Routing to human review."}
        verdicts.append({"claim": None, "verdict": verdict})
        _write_audit_row(customer_id, bot_response, None, verdict, final_response)
    elif not claims:
        # LLM succeeded but found no rate/fee claims in the response
        # If the question was a rate question, the bot evaded it → FALLBACK
        _RATE_KEYWORDS = {"rate", "apr", "apy", "interest", "fee", "percent", "%", "cost", "price"}
        q_words = set(customer_question.lower().split())
        is_rate_question = bool(q_words & _RATE_KEYWORDS)

        if is_rate_question:
            verdict = {"action": "FALLBACK", "correct_value": None, "correct_basis": None,
                       "reason": "Customer asked a rate/fee question but bot provided no specific figure to verify."}
        else:
            verdict = {"action": "PASS", "correct_value": None, "correct_basis": None,
                       "reason": "LLM found no rate or fee claims — nothing to verify."}
        verdicts.append({"claim": None, "verdict": verdict})
        _write_audit_row(customer_id, bot_response, None, verdict, final_response)
    else:
        corrections = []
        for claim in claims:
            verdict = verify_claim(claim, customer_id, f"{customer_question} {bot_response}")
            verdicts.append({"claim": claim, "verdict": verdict})

            if verdict["action"] == "CORRECT":
                final_response = _apply_correction(
                    final_response,
                    claim.get("claim_text", ""),
                    verdict.get("correct_value", ""),
                    verdict.get("correct_basis"),
                )
                corrections.append({
                    "was": claim.get("claim_text", ""),
                    "now": f"{verdict.get('correct_value', '')} {verdict.get('correct_basis') or ''}".strip(),
                })
            _write_audit_row(customer_id, bot_response, claim, verdict, final_response)

    # ── Step 4: Overall action ─────────────────────────────────────────
    all_verdicts = [v["verdict"] for v in verdicts]
    overall      = _overall_action(all_verdicts)

    # ── Step 5: Trust signals (deterministic) ─────────────────────────
    trust = evaluate_trust(verdicts)
    if trust["freshness_gate"] and overall != "FALLBACK":
        overall = "FALLBACK"
        verdicts.append({"claim": None, "verdict": {
            "action": "FALLBACK", "correct_value": None, "correct_basis": None,
            "reason": "Pricing rule is past its shelf life — cannot verify against stale data.",
            "references": []}})
        _write_audit_row(customer_id, bot_response, None, verdicts[-1]["verdict"], _FALLBACK_MESSAGE)

    # Replace entire response on FALLBACK
    if overall == "FALLBACK":
        final_response = _FALLBACK_MESSAGE

    return {
        "verified_at":    ts,
        "input": {
            "customer_id":       customer_id,
            "customer_question": customer_question,
            "bot_response":      bot_response,
        },
        "claims_extracted": claims,
        "verdicts":         verdicts,
        "action":           overall,
        "final_response":   final_response,
        "reliability":      _reliability_score(claims, verdicts),
        "references":       _dedupe_references(verdicts),
        "lineage":          _build_lineage(claims, verdicts, overall, corrections if claims else []),
        "human_review":     _human_review_block(overall, customer_question, bot_response, verdicts),
        "trust_signals":    trust,
        "pii_masked":       pii_masked,
        "audit_log":        _AUDIT_LOG,
    }


# ── CLI modes ──────────────────────────────────────────────────────────

def verify_last_response():
    if not os.path.exists(_LAST_RESPONSE):
        print(f"ERROR: {_LAST_RESPONSE} not found. Send a message via the API first.")
        sys.exit(1)

    with open(_LAST_RESPONSE, encoding="utf-8") as f:
        entry = json.load(f)

    print(f"\nRunning gateway on: {entry.get('customer_question', '')[:70]}")
    print("─" * 70)
    result = run_gateway(entry)

    out_path = os.path.join(_OUTPUT_DIR, "gateway_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    _print_result(result)
    print(f"\nFull result → {out_path}")
    print(f"Audit log  → {_AUDIT_LOG}")


def verify_batch():
    if not os.path.exists(_BATCH_RESPONSES):
        print(f"ERROR: {_BATCH_RESPONSES} not found. Run scripts/run_sample_questions.py first.")
        sys.exit(1)

    with open(_BATCH_RESPONSES, encoding="utf-8") as f:
        batch = json.load(f)

    responses = batch.get("responses", [])
    results   = []
    counts    = {"PASS": 0, "CORRECT": 0, "FALLBACK": 0}
    matches   = 0

    print(f"\nRunning LLM gateway over {len(responses)} responses\n" + "═" * 80)

    for resp in responses:
        print(f"\n[{resp.get('id', '?')}] {resp.get('scenario_type', '')} — {resp.get('customer_question', '')[:55]}")
        result = run_gateway(resp)
        result["test_id"]         = resp.get("id", "")
        result["expected_action"] = resp.get("expected_gateway_action", "")
        result["scenario_type"]   = resp.get("scenario_type", "")
        result["expectation_met"] = (result["action"] == result["expected_action"]) if result["expected_action"] else None
        results.append(result)
        counts[result["action"]] += 1
        if result["expectation_met"]:
            matches += 1

        if result["expected_action"]:
            mark = "✓" if result["expectation_met"] else "✗"
            print(f"  [{mark}] action={result['action']:8}  expected={result['expected_action']:8}")
        else:
            print(f"  action={result['action']:8}  (live LLM answer — no fixed expectation)")
        if result["action"] != "PASS":
            print(f"  final: {result['final_response'][:90]}")

    total = len(results)
    print("\n" + "═" * 80)
    scored = sum(1 for r in results if r["expected_action"])
    if scored:
        print(f"Accuracy : {matches}/{scored} ({100*matches//scored}%)")
    print(f"Actions  : PASS={counts['PASS']}  CORRECT={counts['CORRECT']}  FALLBACK={counts['FALLBACK']}")

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": total, "correct_predictions": matches,
        "action_counts": counts, "results": results,
    }
    out_path = os.path.join(_OUTPUT_DIR, "batch_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"Batch result → {out_path}")
    print(f"Audit log    → {_AUDIT_LOG}")


def _print_result(result: dict):
    print(f"\n{'═'*60}")
    print(f"  GATEWAY: {result['action']}")
    print(f"{'═'*60}")
    print(f"  Customer : {result['input']['customer_id'] or '(general)'}")
    print(f"  Question : {result['input']['customer_question']}")
    print(f"  Bot said : {result['input']['bot_response']}")
    claims = result['claims_extracted']
    print(f"  Claims   : {'LLM extraction failed' if claims is None else len(claims)}")
    print()
    for v in result["verdicts"]:
        claim   = v["claim"]
        verdict = v["verdict"]
        label   = f"[{claim['claim_text']}]" if claim else "[no claim]"
        print(f"  {label:25}  {verdict['action']:8}  {verdict['reason'][:70]}")
        if verdict.get("correct_value"):
            print(f"  {'':25}  → correct: {verdict['correct_value']} {verdict.get('correct_basis') or ''}")
    print()
    print(f"  FINAL RESPONSE: {result['final_response']}")

    rel = result["reliability"]
    print(f"\n  RELIABILITY: {rel['score']}/100 ({rel['label']}) — {rel['reason']}")

    refs = result["references"]
    print(f"\n  REFERENCES ({len(refs)} golden_dataset row(s) consulted):")
    for r in refs:
        print(f"    - {r['file']}: {r['row']}  [{r['why']}]")

    print(f"\n  LINEAGE:")
    for step in result["lineage"]:
        llm_tag = "LLM" if step.get("uses_llm") else "rule-based"
        print(f"    {step['step']}. [{step['stage']} / {llm_tag}] {step['component']}")
        if "description" in step:
            print(f"       {step['description']}")
        if "action" in step and step["stage"] == "verification":
            print(f"       claim={step['claim_text']!r}  action={step['action']}  reason={step['reason'][:70]}")

    hr = result["human_review"]
    if hr["required"]:
        print(f"\n  ⚠ HUMAN REVIEW REQUIRED: {hr['note']}")
        print(f"    Reasons: {'; '.join(hr['reasons'])}")
        if hr["candidate_matches"]:
            print(f"    Candidate matches (unconfirmed, via keyword search):")
            for c in hr["candidate_matches"]:
                print(f"      - {c['row']['product_name']} ({c['row']['product_id']})  matched on: {c['matched_keywords']}")
        else:
            print(f"    No candidate matches found in golden_dataset by keyword search either.")
        print(f"    Probable route: {hr['probable_route']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM-powered rate verification gateway")
    parser.add_argument("--batch", action="store_true", help="Batch-verify all responses.json rows")
    args = parser.parse_args()

    if args.batch:
        verify_batch()
    else:
        verify_last_response()
