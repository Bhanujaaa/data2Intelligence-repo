"""
Trust signals — deterministic, no LLM
=====================================
Explains *why* a verdict can be trusted, using only the data layer:

  provenance   every verified claim points to the exact golden_dataset row(s)
  reliability  tier of the sources consulted (golden_dataset/source_registry.csv)
  freshness    age of the pricing rule used vs. its shelf life
  agreement    do secondary sources (branch FAQ, marketing page) agree with the
               system of record? Conflicts are surfaced, never averaged.

Hard gate: a pricing rule past its shelf life cannot be used to PASS or CORRECT
— the gateway falls back instead.
"""

import csv
import os
from datetime import date, datetime, timezone

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TIER_SCORE = {"system_of_record": 1.0, "approved_policy": 0.85, "internal_wiki": 0.5,
              "marketing": 0.4, "email": 0.3, "unknown": 0.2}
VALUE_TOLERANCE = 0.1


def _load(rel_path: str) -> list[dict]:
    with open(os.path.join(_PROJECT_ROOT, rel_path), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def registry() -> dict[str, dict]:
    return {r["file"]: r for r in _load("golden_dataset/source_registry.csv")}


def _secondary_rows(product_id: str) -> list[dict]:
    reg, rows = registry(), []
    for path, meta in reg.items():
        if not path.startswith("secondary_sources/"):
            continue
        for r in _load(path):
            if r["product_id"] == product_id:
                rows.append({**r, "file": path, "source_tier": meta["source_tier"]})
    return rows


def _num(raw) -> float | None:
    try:
        return float(str(raw).replace("%", "").replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _age_days(iso_date: str, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(iso_date[:10])).days
    except (TypeError, ValueError):
        return None


# ── per-claim signals ─────────────────────────────────────────────────

def provenance(verdict: dict) -> dict:
    refs = verdict.get("references") or []
    if verdict["action"] == "FALLBACK" or not refs:
        return {"score": 0.0, "why": "no confirmed source row"}
    return {"score": 1.0, "why": f"{len(refs)} golden_dataset row(s) cited"}


def reliability(verdict: dict) -> dict:
    reg = registry()
    tiers = [reg.get(r["file"], {}).get("source_tier", "unknown") for r in verdict.get("references") or []]
    if not tiers:
        return {"score": 0.0, "why": "no source"}
    worst = min(tiers, key=lambda t: TIER_SCORE.get(t, 0.2))
    return {"score": TIER_SCORE.get(worst, 0.2), "why": f"weakest source tier: {worst}"}


def freshness(verdict: dict, today: date) -> dict:
    reg = registry()
    life = int(reg["golden_dataset/pricing_rules.csv"]["shelf_life_days"])
    ages = [_age_days(r["row"].get("effective_date", ""), today)
            for r in verdict.get("references") or [] if r["file"].endswith("pricing_rules.csv")]
    ages = [a for a in ages if a is not None]
    if not ages:
        return {"score": 1.0, "why": "no pricing rule used (account or catalog data)", "expired": False}
    age = max(ages)
    if age <= life:
        return {"score": 1.0, "why": f"pricing rule is {age} days old (shelf life {life})", "expired": False}
    if age <= 2 * life:
        return {"score": 0.5, "why": f"pricing rule is {age} days old (shelf life {life})", "expired": False}
    return {"score": 0.0, "why": f"pricing rule is {age} days old — past its {life}-day shelf life", "expired": True}


def agreement(claim: dict | None, verdict: dict) -> dict:
    """Compare the authoritative value with what secondary sources say."""
    if not claim or not claim.get("matched_product_id") or verdict["action"] == "FALLBACK":
        return {"score": 1.0, "why": "nothing to compare", "conflicts": []}
    authoritative = _num(verdict.get("correct_value")) if verdict["action"] == "CORRECT" else _num(claim.get("value"))
    if authoritative is None:
        return {"score": 1.0, "why": "no numeric value to compare", "conflicts": []}
    others = [r for r in _secondary_rows(claim["matched_product_id"])
              if r.get("claim_type") == claim.get("claim_type")]
    if not others:
        return {"score": 1.0, "why": "no secondary source states this", "conflicts": []}
    total, support, conflicts = 1.0, 1.0, []
    for r in others:
        w = TIER_SCORE.get(r["source_tier"], 0.2)
        total += w
        if abs(_num(r["value"]) - authoritative) <= VALUE_TOLERANCE:
            support += w
        else:
            echoed = _num(claim.get("value")) is not None and abs(_num(r["value"]) - _num(claim["value"])) <= VALUE_TOLERANCE
            conflicts.append({
                "file": r["file"], "row_id": r["row_id"], "source_tier": r["source_tier"],
                "value": r["value"], "as_of": r["as_of"], "statement": r["statement"],
                "bot_repeated_this": echoed,
                "resolution": "outranked by golden_dataset (system of record)",
            })
    why = "all sources agree" if not conflicts else \
        f"{len(conflicts)} lower-tier source(s) disagree — system of record wins"
    return {"score": round(support / total, 2), "why": why, "conflicts": conflicts}


# ── whole response ────────────────────────────────────────────────────

def evaluate(verdicts: list[dict], today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    per_claim = []
    for v in verdicts:
        claim, verdict = v["claim"], v["verdict"]
        per_claim.append({
            "claim_text": claim.get("claim_text") if claim else None,
            "action": verdict["action"],
            "provenance": provenance(verdict),
            "reliability": reliability(verdict),
            "freshness": freshness(verdict, today),
            "agreement": agreement(claim, verdict),
        })
    expired = [c for c in per_claim if c["freshness"]["expired"]]
    return {
        "claims": per_claim,
        "freshness_gate": bool(expired),
        "conflicts": [x for c in per_claim for x in c["agreement"]["conflicts"]],
    }
