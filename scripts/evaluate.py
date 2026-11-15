"""Evaluate Divya's phone brain on scripted conversations — quality, latency and token cost.

    python scripts/evaluate.py                # all scenarios → docs/eval_report.md
    python scripts/evaluate.py real_call      # one scenario

Each lead line is sent through the SAME `think()` used on live calls (Groq, compact prompt).
Automatic checks score every reply: answers questions with real facts, never invents times or
discounts, never re-asks, gives the pitch before booking, switches to Hinglish, ends correctly.
"""
from __future__ import annotations

import asyncio
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8")

import httpx  # noqa: E402

from backend.clients import Groq  # noqa: E402
from backend.phone_agent import greeting, respond, system_phone  # noqa: E402

# ── checks ────────────────────────────────────────────────────────────────────
DAYS = r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|somvar|ravivar)\b"
TIME = r"\b\d{1,2}\s?(am|pm|a\.m\.|p\.m\.|baje)\b"


def has(reply: str, *words: str) -> bool:
    r = reply.lower()
    return any(w.lower() in r for w in words)


def check_turn(rule: str, reply: str, out: dict, convo: list[dict]) -> tuple[bool, str]:
    r = reply.lower()
    said_before = " ".join(m["text"].lower() for m in convo if m["role"] == "user")
    if rule == "price":
        return has(r, "ninety-two", "92.4", "ninety two") and has(r, "two point four six", "2.46", "crore", "kror"), "states the ₹92.4 L – ₹2.46 Cr range"
    if rule == "amenities":
        return sum(has(r, w) for w in ("pool", "gym", "clubhouse", "park", "trail", "tennis", "pickleball", "jogging", "cycling", "open")) >= 2, "names real amenities"
    if rule == "schools_hospitals":
        return has(r, "gitam", "stonehill", "nagarjuna") and has(r, "columbia", "manipal", "government hospital", "hospital"), "names nearby schools AND hospitals"
    if rule == "budget_low":
        return has(r, "ninety-two", "92.4", "ninety two") and not re.search(r"\bemi\b.*\d|\d+\s?%", r), "gives entry price, no invented EMI/discount numbers"
    if rule == "no_discount":
        return has(r, "expert") and not re.search(r"\d+\s?(%|percent)|discount of", r), "defers discount to the expert, no numbers"
    if rule == "end":
        return bool(out.get("end")), "ends the call"
    if rule == "not_end":
        return not out.get("end"), "keeps the call going"
    if rule == "hinglish":
        return out.get("lang") == "hi" and has(r, "aap", "hai", "hain", "ke liye", "kya", "bilkul", "theek"), "replies in Hinglish"
    if rule == "ai":
        return has(r, "ai", "assistant"), "admits being an AI assistant"
    if rule == "defer_expert":
        return has(r, "expert"), "defers to the Property Expert"
    if rule == "apology":
        return has(r, "sorry", "apolog", "maaf"), "apologises"
    if rule == "confirm_slot":
        return bool(re.search(DAYS, r)) and has(r, *[d for d in re.findall(DAYS, said_before)] or ["~"]), "confirms the lead's chosen slot"
    raise ValueError(rule)


def global_checks(convo: list[dict]) -> list[tuple[bool, str]]:
    results = []
    # 1. Never propose a day/time the lead didn't say first
    invented = []
    lead_said = ""
    for m in convo:
        if m["role"] == "user":
            lead_said += " " + m["text"].lower()
        else:
            for d in re.findall(DAYS, m["text"].lower()):
                if d not in lead_said:
                    invented.append(d)
            if not re.search(r"\d|baje|\bam\b|\bpm\b|morning|evening|afternoon|subah|shaam|raat", lead_said):
                invented += [x.group(0) for x in re.finditer(TIME, m["text"].lower())]
    results.append((not invented, f"never invents a day/time{' (invented: ' + ', '.join(invented) + ')' if invented else ''}"))
    # 2. Pitch appears before (or with) the callback request
    asks_cb = [i for i, m in enumerate(convo) if m["role"] == "assistant" and has(m["text"], "property expert") and has(m["text"], "day", "time", "when")]
    pitched = [i for i, m in enumerate(convo) if m["role"] == "assistant" and has(m["text"], "74", "seventy-four", "seventy four", "open green", "private valley", "clubhouse")]
    if asks_cb:
        results.append((bool(pitched) and min(pitched) <= asks_cb[0], "gives the pitch before booking the expert"))
    # 3. Doesn't re-ask the budget after the lead stated it
    stated = next((i for i, m in enumerate(convo) if m["role"] == "user" and re.search(r"lakh|lac|crore|budget", m["text"].lower())), None)
    if stated is not None:
        reasked = any(m["role"] == "assistant" and re.search(r"what('s| is) your budget|budget kya", m["text"].lower()) for m in convo[stated + 1:])
        results.append((not reasked, "doesn't re-ask the budget once given"))
    # 4. Short replies (≤ 2 sentences-ish)
    long_ones = [m["text"] for m in convo if m["role"] == "assistant" and len(re.findall(r"[.!?](\s|$)", m["text"])) > 3]
    results.append((not long_ones, "keeps replies short"))
    return results


# ── scenarios: (lead line, [checks on Divya's reply]) ────────────────────────
SCENARIOS: dict[str, list[tuple[str, list[str]]]] = {
    "real_call": [  # the questions from your real phone call
        ("Yeah, sure.", ["not_end"]),
        ("So actually I have a budget of around 70 lakhs.", ["budget_low"]),
        ("Tell me about all the amenities.", ["amenities"]),
        ("What is the price range? Can you please tell me?", ["price"]),
        ("I want to know about nearby hospitals and schools.", ["schools_hospitals"]),
        ("Okay fine, Saturday 11 AM for the expert call.", ["confirm_slot"]),
    ],
    "happy_investor": [
        ("Yes, go ahead.", ["not_end"]),
        ("Investment, budget around one and a half crore.", ["not_end"]),
        ("Yes, Nandi Hills is fine.", ["not_end"]),
        ("December 2029 is okay.", ["not_end"]),
        ("Saturday 11 AM works.", ["confirm_slot"]),
    ],
    "hindi_nri": [
        ("Haan boliye, Hindi mein baat kar sakte hain?", ["hinglish"]),
        ("Family ke liye weekend home chahiye, main Dubai mein rehta hoon.", ["hinglish"]),
        ("Do crore tak chalega.", ["hinglish"]),
        ("Sunday shaam saat baje India time.", ["confirm_slot"]),
    ],
    "budget_low": [
        ("Yes.", ["not_end"]),
        ("My budget is only 70 lakhs.", ["budget_low"]),
        ("Can you give a discount?", ["no_discount"]),
        ("Okay, Friday 6 PM for the expert.", ["confirm_slot"]),
    ],
    "irritated": [
        ("I'm in a meeting, why do you people keep calling?", ["apology"]),
        ("Don't call me again.", ["end", "apology"]),
    ],
    "off_topic": [
        ("Sure. What's the exact price per square foot for a corner plot?", ["defer_expert"]),
        ("Is it better than the Prestige project?", ["not_end"]),
        ("Are you a robot?", ["ai"]),
        ("I want ready-to-move in the city, not this.", []),   # ending politely here is also correct
        ("No thanks, not interested.", ["end"]),
    ],
    "location_far": [
        ("Okay, quickly.", ["not_end"]),
        ("Budget is fine, around 1.5 crore, but Nandi Hills is too far from Indiranagar.", ["not_end"]),
        ("Hmm, as a weekend home maybe.", ["not_end"]),
        ("Monday evening is fine for the expert.", ["confirm_slot"]),
    ],
}

TPM_BUDGET = 5000   # stay under Groq's free 8k tokens/minute on the main model


async def run(name: str, script, groq: Groq, pace: list) -> dict:
    convo = [{"role": "assistant", "text": greeting("Rahul")}]
    turns, passed, total = [], 0, 0
    for line, rules in script:
        # pace requests so the main model isn't rate-limited (otherwise quality drops to fallbacks)
        now = time.time()
        pace[:] = [(t, n) for t, n in pace if now - t < 60]
        while sum(n for _, n in pace) > TPM_BUDGET:
            await asyncio.sleep(2)
            now = time.time()
            pace[:] = [(t, n) for t, n in pace if now - t < 60]
        convo.append({"role": "user", "text": line})
        out = await respond(groq, convo, "Rahul", "Whitefield", (turns[-1]["lang"] if turns else "en") or "en")
        u = out.get("_usage") or {}
        pace.append((time.time(), (u.get("prompt_tokens") or 1400) + (u.get("completion_tokens") or 100)))
        reply = out.get("reply") or "(no reply)"
        convo.append({"role": "assistant", "text": reply})
        res = [(rule, *check_turn(rule, reply, out, convo)) for rule in rules]
        passed += sum(ok for _, ok, _ in res)
        total += len(res)
        turns.append({"lead": line, "aanya": reply, "end": out.get("end"), "lang": out.get("lang"),
                      "latency": out.get("_latency_s"), "usage": u, "checks": res})
        if out.get("end"):
            break
    g = global_checks(convo)
    passed += sum(ok for ok, _ in g)
    total += len(g)
    return {"name": name, "turns": turns, "global": g, "passed": passed, "total": total}


def report(results: list[dict]) -> str:
    allturns = [t for r in results for t in r["turns"]]
    lat = [t["latency"] for t in allturns if t["latency"]]
    pt = [t["usage"].get("prompt_tokens") or 0 for t in allturns if t["usage"]]
    ct = [t["usage"].get("completion_tokens") or 0 for t in allturns if t["usage"]]
    cached = [t["usage"].get("cached_tokens") or 0 for t in allturns if t["usage"]]
    models = {}
    for t in allturns:
        m = (t["usage"] or {}).get("model", "failed")
        models[m] = models.get(m, 0) + 1
    P, T = sum(r["passed"] for r in results), sum(r["total"] for r in results)
    lines = [
        "# Divya phone-brain evaluation", "",
        f"_System prompt ≈ {len(system_phone()) // 4} tokens · {len(allturns)} turns · {time.strftime('%Y-%m-%d %H:%M')}_", "",
        "| Metric | Value |", "|---|---|",
        f"| **Checks passed** | **{P}/{T} ({100 * P // max(T, 1)}%)** |",
        f"| LLM latency per turn | avg {sum(lat) / max(len(lat), 1):.2f}s · max {max(lat or [0]):.2f}s |",
        f"| Prompt tokens per turn | avg {sum(pt) // max(len(pt), 1)} (cached avg {sum(cached) // max(len(cached), 1)}) |",
        f"| Completion tokens per turn | avg {sum(ct) // max(len(ct), 1)} |",
        f"| Models used | {', '.join(f'{k} ×{v}' for k, v in models.items())} |", "",
        "| Scenario | Score |", "|---|---|",
        *[f"| {r['name']} | {r['passed']}/{r['total']} |" for r in results], "",
    ]
    for r in results:
        lines += [f"## {r['name']} — {r['passed']}/{r['total']}", ""]
        for t in r["turns"]:
            lines.append(f"- **Lead:** {t['lead']}")
            lines.append(f"  **Divya:** {t['aanya']}  _({t['latency']}s, {(t['usage'] or {}).get('model', '?')})_")
            for rule, ok, why in t["checks"]:
                lines.append(f"  - {'✅' if ok else '❌'} {why}")
        for ok, why in r["global"]:
            lines.append(f"- {'✅' if ok else '❌'} whole call: {why}")
        lines.append("")
    return "\n".join(lines)


async def main() -> None:
    names = sys.argv[1:] or list(SCENARIOS)
    pace: list = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=25)) as http:
        groq = Groq(http)
        results = []
        for n in names:
            print(f"▶ {n}", flush=True)
            r = await run(n, SCENARIOS[n], groq, pace)
            print(f"  {r['passed']}/{r['total']}", flush=True)
            results.append(r)
    md = report(results)
    out = ROOT / "docs" / "eval_report.md"
    out.write_text(md, encoding="utf-8", newline="\n")
    print("\n" + md.split("## ")[0])
    print(f"Full report: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
