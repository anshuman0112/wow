"""Lead score 0-100, computed by code from what the lead actually said (not a guess by the AI).

The AI only reports per-checkpoint verdicts ("Yes / Stretch / No…") with the lead's own words as evidence.
This module turns them into points using the campaign's scoring rules (editable on the Settings page),
so the same answers always give the same score — on every call.

    Budget "Stretch"  → 12 of 25 points   evidence: "around 80 lakh"
    Location "Yes"    → 20 of 20 points   evidence: "Nandi Hills is fine"
    …
    tone irritated    → -10
    total             → 0..100 → Hot / Warm / Cold by the pass marks
"""
from __future__ import annotations

_OVERRIDE: dict | None = None   # set from the Settings page (see backend/config_store.py)


def rules() -> dict:
    """The active scoring rules: Settings-page overrides on top of the campaign defaults."""
    from .campaign import data
    base = dict(data().get("scoring") or {})
    return {**base, **(_OVERRIDE or {})}


def _verdict(text: object) -> str:
    """'Yes - comfortable…' → 'yes'; 'Stretch, 80 lakh' → 'partial'; 'No' → 'no'; else 'unknown'."""
    t = str(text or "").strip().lower()
    if not t or t.startswith(("unknown", "n/a", "not discussed", "not asked", "none")):
        return "unknown"
    if t.startswith(("yes", "comfortable", "fits", "ok", "fine")):
        return "yes"
    if t.startswith(("stretch", "hesitant", "unsure", "maybe", "partly", "partial", "somewhat")):
        return "partial"
    if t.startswith(("no", "not")):
        return "no"
    return "unknown"


def compute(analysis: dict, rules: dict) -> dict:
    """→ {"score", "tier", "breakdown": [{key, label, points, max, verdict, evidence}]}"""
    pts = rules.get("points", {})
    ev = analysis.get("evidence") if isinstance(analysis.get("evidence"), dict) else {}
    rows = []

    def add(key: str, verdict: str, detail: str = ""):
        r = pts.get(key)
        if not r:
            return
        full, half = r.get("max", 0), r.get("partial", 0)
        got = full if verdict == "yes" else half if verdict == "partial" else 0
        rows.append({"key": key, "label": r.get("label", key), "points": got, "max": full, "verdict": verdict,
                     "detail": detail, "evidence": str(ev.get(key) or "")[:160]})

    intent = str(analysis.get("intent") or "")
    add("intent", "yes" if intent and not intent.lower().startswith("unknown") else "unknown", intent)
    add("geography", _verdict(analysis.get("geography_fit")), str(analysis.get("geography_fit") or ""))
    add("budget", _verdict(analysis.get("budget_fit")), str(analysis.get("budget_fit") or ""))
    add("timeline", _verdict(analysis.get("timeline_fit")), str(analysis.get("timeline_fit") or ""))
    dm = analysis.get("decision_maker") or "unknown"
    add("decision", "yes" if dm in ("self", "spouse", "family") else "partial" if dm == "someone_else" else "unknown", dm)
    cb = str(analysis.get("callback_time") or "").strip()
    add("callback", "yes" if cb else "unknown", cb)

    tone_key = analysis.get("sentiment_end") or ""
    tone = int((rules.get("tone") or {}).get(tone_key, 0))
    if tone:
        rows.append({"key": "tone", "label": f"Tone at the end: {tone_key}", "points": tone, "max": 0,
                     "verdict": tone_key, "detail": "", "evidence": ""})
    score = max(0, min(100, sum(r["points"] for r in rows)))
    if analysis.get("do_not_call") is True:
        score = 0
    tiers = rules.get("tiers") or {"hot": 70, "warm": 40}
    tier = "hot" if score >= tiers.get("hot", 70) else "warm" if score >= tiers.get("warm", 40) else "cold"
    # Must-haves for "hot" (e.g. the budget has to fit): a high score with a budget gap is still only warm.
    musts = rules.get("hot_requires") or []
    missing = [r["label"] for r in rows if r["key"] in musts and r["verdict"] != "yes"]
    if tier == "hot" and missing:
        tier = "warm"
    return {"score": score, "tier": tier, "breakdown": rows, "hot_blocked_by": missing}


def profile_fields(analysis: dict, rules: dict) -> dict:
    """Everything the sales team needs from one call, ready to save on the call and the lead."""
    s = compute(analysis, rules)
    raw = analysis.get("objections")
    if isinstance(raw, str):   # some models return "a; b" instead of a list
        raw = [x.strip() for x in raw.replace("\n", ";").split(";") if x.strip()]
    objections = raw if isinstance(raw, list) else []
    return {"score": s["score"], "interest": s["tier"], "score_breakdown": s["breakdown"],
            "objections": [str(o)[:200] for o in objections][:8],
            "decision_maker": analysis.get("decision_maker") or "unknown",
            "next_action": str(analysis.get("next_action") or "")[:300] or None}
