"""Most-asked questions without the LLM, plus deterministic guardrails on LLM replies.

A lead's turn that is a plain property question ("what amenities?", "price kitna hai?", "schools nearby?")
is answered from facts (cached in Redis, 0 tokens), followed by the next script question chosen by a
tracker of what this call already covered — so a cached answer never re-asks an answered question.
"""
from __future__ import annotations

import re

from .campaign import data

INTENTS: dict[str, str] = {
    "rate": r"\b(per (sq|square)|sq ?ft rate|rate per|per sqft|psf)\b",
    "price": r"\b(price|pricing|cost|rate|kitna|kitne|kitni|kimat|keemat|daam|starting|how much)\b",
    "size": r"\b(size|sizes|sq ?ft|square (feet|foot)|acre|acres|how big|kitna bada)\b",
    "amenities": r"\b(amenit\w*|facilit\w*|clubhouse|club house|pool|gym|sports|parks?|features)\b",
    "schools": r"\b(schools?|colleges?|education|university)\b",
    "hospitals": r"\b(hospitals?|clinics?|medical|healthcare|doctors?)\b",
    "location": r"\b(where|location|located|kahan|address|airport|distance|how far|kitni door|connectivity)\b",
    "possession": r"\b(possession|handover|hand over|ready to move|completion|kab tak|delivery date)\b",
    "rera": r"\b(rera|approvals?|legal|registered|registration)\b",
    "payment": r"\b(emi|loan|loans|payment plan|installments?|discount|discounts|offer|offers)\b",
}
QUESTION = r"(\?|\b(what|which|how|where|when|is there|are there|tell me|tell|details|any|know|info|information|explain|share|" \
           r"kya|kitna|kitne|kahan|kab|batao|bataiye|batayiye|jaankari)\b)"
# Turns that carry the lead's own answers/decisions must go to the LLM, not the cache.
STATEMENT = r"\b(budget|lakh|lakhs|lac|lacs|crore|crores|chalega|not interested|call me|don'?t call|busy|meeting|" \
            r"invest\w*|weekend home|self use|monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|" \
            r"\d+\s?(am|pm)|baje|yes|no|okay|ok|fine|theek|haan|nahi)\b"
HINDI = r"\b(kya|hai|hain|kitna|kitne|kahan|kab|batao|bataiye|aap|mujhe|hum|nahi|haan|chahiye|ke liye|chalega|tak|hoon|" \
        r"rehta|boliye|baat|theek|accha|achha|ji|shaam|subah|baje|dekh|raha|rahe)\b"


SIZE_WORDS = r"\b(size|sizes|acre|acres|how big|plots?)\b"


def detect(utterance: str) -> list[str]:
    """Return FAQ intents if this turn is purely a property question, else []."""
    u = utterance.lower()
    # "What is the budget / price range / kitna hai?" is always a price question, even with stray words like "lakh".
    if re.search(r"\b(what('s| is)|tell me|kya hai|kitna|kitne|how much)\b.{0,25}\b(budget|price|range|cost|rate)\b", u) \
            and not re.search(r"\b(my|mera|meri|i have|hamara)\b.{0,15}\bbudget\b", u):
        extra = [k for k, pat in INTENTS.items() if k not in ("price", "rate") and re.search(pat, u)]
        if re.search(INTENTS["rate"], u) and not re.search(SIZE_WORDS, u):
            extra = [k for k in extra if k != "size"]
        return ["price"] + extra[:2] \
            + (["rate"] if re.search(INTENTS["rate"], u) else [])
    if not re.search(QUESTION, u) or re.search(STATEMENT, u) or len(u.split()) > 22:
        return []
    if re.search(r"\b(exact|exactly|corner|specific|which plot|negotiat)", u):
        return []   # needs a careful "the expert will confirm" answer from the LLM, not a general fact
    found = [k for k, pat in INTENTS.items() if re.search(pat, u)]
    if "rate" in found and "size" in found and not re.search(SIZE_WORDS, u):
        found.remove("size")   # "price per square feet" is a rate question, not a plot-size one
    return found[:3]


def lang_of(utterance: str, current: str = "en") -> str:
    return "hi" if re.search(HINDI, utterance.lower()) else current


# How each checkpoint question looks when Aanya asks it (English + Hinglish).
ASKED = {
    "intent": r"weekend home (or|ya) (as |an )?investment|weekend home.*investment",
    "geography": r"comfortable with .*(nandi|devanahalli|location|area)|(nandi|devanahalli).*(theek|comfortable)",
    "budget": r"(fit|work|within|suit)\w* .{0,25}budget|budget mein|budget ke hisaab",
    "timeline": r"(december 2029|possession|timeline).{0,60}(comfortable|okay|work|theek)",
}


def covered(messages: list[dict]) -> set[str]:
    """What this call has already covered, read from the conversation itself."""
    lead = " ".join(m["text"].lower() for m in messages if m["role"] == "user")
    aanya = " ".join(m["text"].lower() for m in messages if m["role"] == "assistant")
    c = set()
    for step, pat in ASKED.items():
        for i, m in enumerate(messages[:-1]):
            if m["role"] == "assistant" and re.search(pat, m["text"].lower()) and \
                    any(x["role"] == "user" for x in messages[i + 1:]):
                c.add(step)
                break
    if re.search(r"invest|weekend|self.?use|family|own use|khud|apne liye|rehne", lead):
        c.add("intent")
    if re.search(r"lakh|lac|crore|budget", lead):
        c.add("budget")
    if re.search(r"nandi|devanahalli|location (is )?(fine|ok)|far|door", lead) or re.search(r"comfortable with the nandi|area.*theek", aanya) and len(messages) > 6:
        c.add("geography")
    if re.search(r"2029|possession|timeline|no hurry|ready to move", lead):
        c.add("timeline")
    # Only the real lifestyle pitch counts — listing "74% open space" among amenities is not the pitch.
    if re.search(r"private valley|like-minded|like minded", aanya):
        c.add("pitch")
    if re.search(r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow)", lead) and "pitch" in c:
        c.add("callback")
    return c


def next_question(messages: list[dict], lang: str) -> str:
    done = covered(messages)
    nq = data()["nextQuestion"]
    # Don't repeat a question we asked in the last two replies — if the lead skipped it, move on.
    recent = " ".join(m["text"] for m in messages[-4:] if m["role"] == "assistant")
    pending = [s for s in ("intent", "geography", "budget", "timeline", "pitch", "callback") if s not in done]
    for step in pending:
        if nq[step][lang] not in recent and nq[step]["en"] not in recent:
            return nq[step][lang]
    return nq[pending[0] if pending else "callback"][lang]


def answer(intents: list[str], lang: str, cached: dict[str, str] | None = None) -> str:
    faq = data()["faq"]
    return " ".join((cached or {}).get(i) or faq[i][lang] for i in intents)


# ── budget objection (deterministic, 0 tokens) ──────────────────────────────
WORD_NUM = {"seventy": 70, "eighty": 80, "ninety": 90, "sixty": 60, "fifty": 50, "forty": 40, "hundred": 100,
            "one": 1, "two": 2, "one and a half": 1.5, "half": 0.5}
ENTRY_LAKH = 92.4


def budget_lakh(text: str) -> float | None:
    """Largest budget the lead mentions, in lakh (handles '75 lacs', '75 to 80 lakh', '1.5 crore', 'seventy lakh')."""
    t = text.lower().replace(",", "")
    vals = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:to|-|–)?\s*(\d+(?:\.\d+)?)?\s*(lakh|lakhs|lac|lacs|l\b|crore|crores|cr\b)", t):
        n = float(m.group(2) or m.group(1))
        vals.append(n * 100 if m.group(3).startswith("cr") else n)
    for w, n in sorted(WORD_NUM.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{w}\s+(lakh|lakhs|lac|lacs|crore|crores)\b", t):
            unit = re.search(rf"\b{w}\s+(lakh|lakhs|lac|lacs|crore|crores)\b", t).group(1)
            vals.append(n * 100 if unit.startswith("cr") else n)
    return max(vals) if vals else None


def _said(messages: list[dict]) -> str:
    return " ".join(m["text"] for m in messages[:-1] if m["role"] == "assistant").lower()


def budget_objection(messages: list[dict], lang: str) -> str | None:
    """Budget below the entry price -> benefit-led persuasion in up to two steps, then a graceful exit.

    Persuasive but truthful: staged payments, plot loans via the expert, early entry into a growing
    corridor, the exact (small) gap. Never invents EMI amounts, discounts or guaranteed returns."""
    last = messages[-1]["text"] if messages and messages[-1]["role"] == "user" else ""
    b = budget_lakh(last)
    if b is None or b >= ENTRY_LAKH:
        return None
    said = _said(messages)
    amount, gap = f"{int(b)} lakh", ENTRY_LAKH - b
    gap_en = f"about {round(gap)} lakh" if gap >= 1 else "less than a lakh"
    gap_hi = f"lagbhag {round(gap)} lakh" if gap >= 1 else "ek lakh se bhi kam"
    if "the gap is only" in said or "gap sirf" in said:                       # step 3: accept politely
        return ("Completely understood, and thank you for being open with me. I'll note your budget, and if a suitable "
                "option comes up, our team will reach out. Have a lovely day!") if lang == "en" else \
               ("Bilkul samajh gayi, openly batane ke liye shukriya. Main aapka budget note kar leti hoon, koi suitable "
                "option aaya toh hamari team aapse contact karegi. Aapka din shubh ho!")
    if "staged" in said:                                                       # step 2: the gap is small
        return (f"I hear you. Honestly, the gap is only {gap_en}, and with staged payments plus a plot loan, many of our "
                "buyers bridge it comfortably. There's no obligation at all. Would a ten-minute call with our Property "
                "Expert to see the actual numbers be worth it?") if lang == "en" else \
               (f"Main samajh rahi hoon. Sach kahun toh gap sirf {gap_hi} ka hai, aur staged payments aur plot loan ke saath "
                "bahut se buyers ise aaraam se manage kar lete hain. Koi obligation nahi hai. Kya hamare Property Expert ke "
                "saath das minute ki call mein actual numbers dekhna theek rahega?")
    return (f"Understood, and many of our buyers started with a budget close to {amount}. Payments here are staged with "
            "construction until December 2029, so you don't pay it all upfront, and our Property Expert can arrange "
            "plot-loan options to keep the monthly outgo light. You'd also be entering early in North Bengaluru's airport "
            "and STRR growth corridor. Shall I have our expert show you a payment plan around your budget?") if lang == "en" else \
           (f"Samajh gayi, hamare kaafi buyers ne bhi {amount} ke aas-paas ke budget se shuru kiya tha. Yahan payments "
            "December 2029 tak construction ke saath staged hain, sab upfront nahi dena hota, aur hamare Property Expert "
            "plot-loan options arrange kar sakte hain taaki monthly outgo halka rahe. Aur aap North Bengaluru ke airport aur "
            "STRR growth corridor mein early enter karenge. Kya hamare expert aapke budget ke hisaab se payment plan dikhayen?")


LOCATION_PUSHBACK = re.compile(
    r"(too far|very far|bahut door|kaafi door|far away|far from (the )?(city|office|home|my)|not comfortable with (the )?"
    r"(location|area|place)|location (is )?(not|bad|an issue|a problem)|don'?t like (the )?(location|area)|"
    r"not (a )?good location|prefer (somewhere|something) (closer|in the city)|location (theek|accha) nahi)", re.I)


def location_objection(messages: list[dict], lang: str) -> str | None:
    """Budget fits but location doesn't -> reframe as a weekend escape + growth corridor; second time, offer the expert."""
    last = messages[-1]["text"] if messages and messages[-1]["role"] == "user" else ""
    if not LOCATION_PUSHBACK.search(last) or re.search(r"\bhow far\b|kitna door|kitni door", last, re.I):
        return None
    if "weekend escape" in _said(messages):                                    # already countered once
        return ("That's completely fair. Our Property Expert can also show how buyers hold it purely as an investment, "
                "without needing to visit often. Would a short call with them be useful?") if lang == "en" else \
               ("Bilkul theek hai. Hamare Property Expert yeh bhi bata sakte hain ki buyers ise sirf investment ki tarah kaise "
                "rakhte hain, bina baar baar aaye. Kya unke saath ek short call useful rahegi?")
    return ("That's fair, and it's exactly why most of our buyers see it as a weekend escape rather than a daily commute: "
            "it's about thirty minutes from the airport, ten minutes from the STRR and fifteen minutes from the Nandi Hills "
            "foothills. And with the airport and STRR corridor growing fast, early buyers get strong future exposure. Would it "
            "work for you as a weekend home or an investment?") if lang == "en" else \
           ("Bilkul sahi baat hai, isiliye hamare zyada buyers ise daily commute nahi, weekend escape ki tarah dekhte hain: "
            "airport se lagbhag thirty minute, STRR se das minute aur Nandi Hills foothills se pandrah minute. Aur airport aur "
            "STRR corridor tezi se grow ho raha hai, toh early buyers ko achha future exposure milta hai. Kya yeh aapke liye "
            "weekend home ya investment ke roop mein kaam karega?")


def fallback_reply(messages: list[dict], lang: str) -> str:
    """Used only if every LLM attempt fails (e.g. free-tier rate limit) — never 'say that once more'."""
    last = (messages[-1]["text"] if messages and messages[-1]["role"] == "user" else "").lower()
    if re.search(r"not interested|don'?t call|no thanks|nahi chahiye", last):
        return "Completely understood. Thank you for your time, and have a lovely day!" if lang == "en" else \
               "Bilkul samajh gayi. Aapke time ke liye dhanyavaad!"
    obj = budget_objection(messages, lang)
    if obj:
        return obj
    if re.search(QUESTION, last):
        intents = detect(last) or [k for k, pat in INTENTS.items() if re.search(pat, last)][:2]
        if intents:   # answer from facts even when the LLM is unavailable
            return f"{answer(intents, lang)} {next_question(messages, lang)}"
        lead_in = "That's a good question; our Property Expert will share the exact details." if lang == "en" else \
                  "Achha sawaal hai; exact details hamare Property Expert batayenge."
        return f"{lead_in} {next_question(messages, lang)}"
    return f"{'Understood.' if lang == 'en' else 'Samajh gayi.'} {next_question(messages, lang)}"


# ── guardrails applied to every LLM reply ───────────────────────────────────
DAYS = r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow)\b"
TIMES = r"\b\d{1,2}(:\d{2})?\s?(am|pm|a\.m\.|p\.m\.|baje)\b"


def guard(reply: str, messages: list[dict], lang: str) -> str:
    """Fix the two failure modes the evaluation found: invented slots and a skipped pitch."""
    lead = " ".join(m["text"].lower() for m in messages if m["role"] == "user")
    r = reply
    lead_gave_slot = bool(re.search(DAYS, lead) or re.search(r"next week|\bkal\b|parso", lead))
    lead_gave_time = re.search(r"\d|baje|am\b|pm\b|morning|evening|afternoon|subah|shaam|dopahar|raat", lead)
    invented = [d for d in re.findall(DAYS, r.lower()) if d not in lead] + \
               ([m.group(0) for m in re.finditer(TIMES, r.lower())] if not lead_gave_time else [])
    asks_expert = re.search(r"property expert|expert", r.lower()) and re.search(r"\b(day|time|when|kab|kaunsa)\b|\?", r.lower())
    lead_wants_expert = re.search(r"\b(call me|callback|call back|expert|schedule|baat karwa)", lead)
    missing = {"intent", "geography", "budget", "timeline"} - covered(messages)
    if (asks_expert or invented) and missing and not lead_gave_slot and not lead_wants_expert:
        # The PDF flow: qualify on all 4 checkpoints before the pitch and the CTA.
        return next_question(messages, lang)
    if invented:
        # Never propose a slot the lead didn't choose — ask them instead.
        r = data()["nextQuestion"]["pitch"][lang] if "pitch" not in covered(messages) else \
            ("What day and time would suit a short call with our Property Expert?" if lang == "en"
             else "Hamare Property Expert ke saath call ke liye kaunsa din aur time theek rahega?")
    elif asks_expert and not lead_gave_slot and "pitch" not in covered(messages + [{"role": "assistant", "text": r}]):
        # The PDF requires the pitch before the CTA.
        r = data()["nextQuestion"]["pitch"][lang]
    return r
