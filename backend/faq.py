"""Most-asked questions without the LLM, plus deterministic guardrails on LLM replies.

A lead's turn that is a plain property question ("what amenities?", "price kitna hai?", "schools nearby?")
is answered from facts (cached in Redis, 0 tokens), followed by the next script question chosen by a
tracker of what this call already covered — so a cached answer never re-asks an answered question.
"""
from __future__ import annotations

import re

from .campaign import data


def _questions() -> dict:
    """Divya's questions, as set on the Settings page (campaign defaults until changed)."""
    from . import config_store
    return config_store.questions()

INTENTS: dict[str, str] = {
    "rate": r"\b(per (sq|square)|sq ?ft rate|rate per|per sqft|psf)\b",
    "price": r"\b(price|pricing|cost|rate|kitna|kitne|kitni|kimat|keemat|daam|starting|how much)\b(?!\s+(door|dur|time|der|minute))",
    "size": r"\b(size|sizes|sq ?ft|square (feet|foot)|acre|acres|how big|kitna bada)\b",
    "amenities": r"\b(amenit\w*|facilit\w*|clubhouse|club house|pool|gym|sports|parks?|features)\b",
    "schools": r"\b(schools?|colleges?|education|university|near ?by|surrounding)\b",
    "hospitals": r"\b(hospitals?|clinics?|medical|healthcare|doctors?|near ?by|surrounding)\b",
    "location": r"\b(where|location|located|kahan|address|airport|distance|how far|kitni door|connectivity)\b",
    # Possession, as people really ask it on calls ("position" = how phone recognition often hears "possession").
    "possession": r"\b(possession|position|handover\w*|handing over|hand(ed)? over|ready to move|completion|kab tak|"
                  r"delivery date|deliver\w*|(possession|position|station|project|delivery|handover) timeline|"
                  r"(when|by when|how soon).{0,40}\b(ready|done|complete\w*|finish\w*|deliver\w*|hand\w*|get (the )?(house|plot|home|keys))|"
                  r"move in|keys)\b",
    "rera": r"\b(rera|approvals?|legal|registered|registration)\b",
    "payment": r"\b(emi|loan|loans|payment plan|installments?|discount|discounts|offer|offers)\b",
    "advantages": r"\b(advantages?|benefits?|usp|why (this|here|should i|buy)|appreciation|growth|investment potential)\b",
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
    """Return FAQ intents if this turn is a property question, else [].
    "Yes, that works. Can you tell me when the possession is?" -> the question part is answered too."""
    found = _detect(utterance)
    if found:
        return found
    # A yes/no or a statement followed by a question: look at each sentence on its own.
    parts = [x for x in re.split(r"(?<=[.?!])\s+|,\s*(?=(?:no one |)(?:can|could|please|when|what|how|where|tell)\b)",
                                 utterance, flags=re.I) if x and x.strip()]
    for part in reversed(parts if len(parts) > 1 else []):
        found = _detect(part)
        if found:
            return found
    return []


# Topic words the phone's speech recognition often gets slightly wrong ("posession", "amenties", "hospitel").
# Each word of the lead's sentence that is a close spelling match is corrected before the topic is detected.
TOPIC_WORDS = ["possession", "amenities", "amenity", "clubhouse", "hospital", "hospitals", "school", "schools",
               "college", "price", "pricing", "budget", "loan", "loans", "installment", "installments", "location",
               "located", "airport", "distance", "rera", "registered", "approval", "approvals", "handover",
               "delivery", "deliver", "completion", "facilities", "facility", "swimming", "gym", "size", "sizes"]
SPOKEN_FIXES = {"position": "possession", "posession": "possession", "possesion": "possession", "station": "possession",
                "pro session": "possession", "e m i": "emi", "emis": "emi", "a menities": "amenities",
                "amenties": "amenities", "club house": "clubhouse", "rara": "rera", "rera's": "rera"}


def correct_words(text: str) -> str:
    """Fix common speech-recognition slips so the question is still understood (no AI needed)."""
    import difflib
    t = " " + text.lower() + " "
    for wrong, right in SPOKEN_FIXES.items():
        # "railway station" / "metro station" are places, not a misheard "possession"
        guard = r"(?<!railway )(?<!metro )(?<!train )(?<!bus )(?<!police )(?<!petrol )" if wrong == "station" else ""
        t = re.sub(rf"{guard}\b{re.escape(wrong)}\b", right, t)
    out = []
    for w in t.split():
        core = re.sub(r"[^a-z']", "", w)
        if len(core) >= 5 and core not in TOPIC_WORDS:
            near = difflib.get_close_matches(core, TOPIC_WORDS, n=1, cutoff=0.84)
            if near:
                w = w.replace(core, near[0])
        out.append(w)
    return " ".join(out)


def _detect(utterance: str) -> list[str]:
    u = correct_words(utterance).strip()
    # A question that merely starts with "No," / "Yes," / "No one," is still a question: drop that lead-in.
    if re.search(QUESTION, u):
        u = re.sub(r"^((yes|no|no one|okay|ok|haan|nahi|so|and|actually|like)\b[\s,.]*)+", "", u)
    # "What is the budget / price range / kitna hai?" is always a price question, even with stray words like "lakh".
    if re.search(r"\b(what('s| is)|tell me|kya hai|kitna|kitne|how much)\b.{0,25}\b(budget|price|range|cost|rate)\b", u) \
            and not re.search(r"\b(my|mera|meri|i have|hamara)\b.{0,15}\bbudget\b", u):
        extra = [k for k, pat in INTENTS.items() if k not in ("price", "rate") and re.search(pat, u)]
        if re.search(INTENTS["rate"], u) and not re.search(SIZE_WORDS, u):
            extra = [k for k in extra if k != "size"]
        return ["price"] + extra[:2] \
            + (["rate"] if re.search(INTENTS["rate"], u) else [])
    # A short noun phrase about a topic ("the EMI plan and the loan", "handover of the project") is a question too.
    topic_only = len(u.split()) <= 8 and any(re.search(INTENTS[k], u) for k in ("payment", "possession", "amenities",
                                                                                   "schools", "hospitals", "rera")) \
        and not re.search(r"\b(i|i'm|im|i am|my|we|we're|our|mera|main)\b", u)   # "I'm a doctor…" is about the lead, not a question
    if (not re.search(QUESTION, u) and not topic_only) or re.search(STATEMENT, u) or len(u.split()) > 30:
        return []
    if re.search(r"\b(exact|exactly|corner|specific|which plot|negotiat)", u):
        return []   # needs a careful "the expert will confirm" answer from the LLM, not a general fact
    found = [k for k, pat in INTENTS.items() if re.search(pat, u)]
    if "rate" in found and "size" in found and not re.search(SIZE_WORDS, u):
        found.remove("size")   # "price per square feet" is a rate question, not a plot-size one
    return found[:3]


def lang_of(utterance: str, current: str = "en") -> str:
    return "hi" if re.search(HINDI, utterance.lower()) else current


# How each checkpoint question looks when Divya asks it (English + Hinglish).
ASKED = {
    "intent": r"weekend home (or|ya) (as |an )?investment|weekend home.*investment",
    "geography": r"comfortable with .*(nandi|devanahalli|location|area)|(nandi|devanahalli).*(theek|comfortable)",
    "budget": r"(fit|work|within|suit)\w* .{0,25}budget|budget mein|budget ke hisaab",
    "timeline": r"(december 2029|possession|timeline).{0,60}(comfortable|okay|work|theek)",
    "decision": r"anyone else .{0,40}decision|decision mein koi|who (else )?(will )?decide",
}


def _is_question(text: str) -> bool:
    t = text.strip().lower()
    return t.endswith("?") or bool(re.match(r"(how|what|when|where|which|why|is |are |can |could |do |does |tell me|please tell)", t))         or bool(detect(text))   # a topic request ("Colleges and hospitals.") asks for information, it answers nothing


def answer_part(text: str) -> str:
    """The parts of a lead's turn that ANSWER something: "Yes. It will work for me, but can you tell me the
    amenities" -> "Yes. It will work for me". Pure questions or topic requests -> ""."""
    parts = re.split(r"(?<=[.!?])\s+|,?\s+\b(?:but|and also|also)\b\s+", text.strip(), flags=re.I)
    return " ".join(x for x in parts if x and x.strip() and not _is_question(x)).strip()


def covered(messages: list[dict]) -> set[str]:
    """What this call has already covered, read from the conversation itself."""
    # Only the lead's ANSWERS count: "How far is Nandi Hills?" is a question, not "location is fine".
    lead = " ".join(answer_part(m["text"]).lower() for m in messages if m["role"] == "user")
    aanya = " ".join(m["text"].lower() for m in messages if m["role"] == "assistant")
    c = set()
    qs = _questions()
    for step in ("intent", "geography", "budget", "timeline", "decision"):
        pat = ASKED.get(step, r"$^")
        # the exact question text from Settings also counts (so reworded questions are still recognised)
        heads = [re.escape(qs[step][lang].lower().replace("-", " ")[:30]) for lang in ("en", "hi") if qs.get(step, {}).get(lang)]
        for i, m in enumerate(messages[:-1]):
            said = m["text"].lower().replace("-", " ")
            if m["role"] == "assistant" and (re.search(pat, said) or any(re.search(h, said) for h in heads)) and \
                    any(x["role"] == "user" and answer_part(x["text"]) for x in messages[i + 1:]):
                c.add(step)
                break
    if re.search(r"invest|weekend|self.?use|family|own use|khud|apne liye|rehne", lead):
        c.add("intent")
    if re.search(r"lakh|lac|crore|budget|(range|price|pricing) (works|is fine|is ok|is okay|is good|suits)|affordable|"
                 r"(that|it) (works|fits) (for me|in my budget)", lead):
        c.add("budget")
    if re.search(r"nandi|devanahalli|north bangalore|north bengaluru|(location|area|place|side|corridor|airport)"
                 r".{0,25}(fine|ok|okay|good|works|comfortable|no problem)|comfortable with (the )?(location|area|place)|far|door", lead) or re.search(r"comfortable with the nandi|area.*theek", aanya) and len(messages) > 6:
        c.add("geography")
    if re.search(r"2029|possession|timeline|no hurry|no rush|can wait|ready to move|december .{0,20}(fine|ok|okay|works)", lead):
        c.add("timeline")
    if re.search(r"\b(my )?(wife|husband|spouse|partner|parents|family|brother|sister)\b.{0,30}(decide|decision|together|and i|with me)|"
                 r"(i|me) (alone|myself)|i (will )?decide|just me|only me|no one else", lead):
        c.add("decision")
    # Only the real lifestyle pitch counts — listing "74% open space" among amenities is not the pitch.
    if re.search(r"private valley|like-minded|like minded", aanya):
        c.add("pitch")
    if re.search(r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow)", lead) and "pitch" in c:
        c.add("callback")
    return c


# After the pitch the only goal is the Property Expert call time (the PDF's CTA). Asked in two wordings so it
# never sounds like a loop; after three asks without a time, Divya closes politely instead of repeating.
TIME_ASK = {
    "en": ["What day and time would suit you for a short call with our Property Expert?",
           "When should our Property Expert call you? Just tell me a day and a time that works for you."],
    "hi": ["Hamare Property Expert ke saath short call ke liye aapko kaunsa din aur time theek rahega?",
           "Hamare Property Expert aapko kab call karein? Bas ek din aur time bata dijiye."],
}
CTA_CLOSE = {
    "en": "No problem at all. Our Property Expert will reach out at a convenient time. Thank you for your time, and have a lovely day!",
    "hi": "Koi baat nahi. Hamare Property Expert aapko suvidha ke time par call karenge. Aapke time ke liye dhanyavaad, aapka din shubh ho!",
}
_TIME_ASKED = re.compile(r"(day and (a )?time|din aur time|kab call karein|what day|kaunsa din)", re.I)


def cta_question(messages: list[dict], lang: str) -> str:
    asked = sum(1 for m in messages if m["role"] == "assistant" and _TIME_ASKED.search(m["text"]))
    if asked >= 3:
        return CTA_CLOSE[lang]
    last = next((m["text"] for m in reversed(messages) if m["role"] == "assistant"), "")
    options = TIME_ASK[lang]
    pick = options[asked % 2]
    return options[(asked + 1) % 2] if pick in last else pick


def next_question(messages: list[dict], lang: str) -> str:
    done = covered(messages)
    nq = _questions()
    if "pitch" in done and "callback" not in done:
        return cta_question(messages, lang)
    # Don't repeat a question we asked in the last two replies — if the lead skipped it, move on.
    recent = " ".join(m["text"] for m in messages[-4:] if m["role"] == "assistant")
    pending = [s for s in ("intent", "geography", "budget", "timeline", "decision", "pitch", "callback") if s not in done]
    # The lead interrupted with a question of their own: after answering it, come back to the question Divya
    # was asking (at most twice per checkpoint), instead of silently skipping it.
    last_user = next((m["text"] for m in reversed(messages) if m["role"] == "user"), "")
    interrupted = "?" in last_user or bool(detect(last_user))
    if interrupted and pending and pending[0] not in ("pitch", "callback"):
        q = nq[pending[0]][lang]
        times = sum(1 for m in messages if m["role"] == "assistant" and (q in m["text"] or nq[pending[0]]["en"] in m["text"]))
        if times < 2:
            back = ("Coming back to my question: " if lang == "en" else "Mere sawaal par wapas aate hain: ") if times else ""
            return back + q
    for step in pending:
        if step == "callback":
            return cta_question(messages, lang)
        if nq[step][lang] not in recent and nq[step]["en"] not in recent:
            return nq[step][lang]
    if not pending or pending[0] == "callback":
        return cta_question(messages, lang)
    return nq[pending[0]][lang]


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
        return (f"I hear you. Honestly, the gap is only {gap_en}, and with staged payments plus a plot loan many buyers "
                "bridge it comfortably. No obligation: would a ten-minute call with our Property Expert to see the numbers help?") if lang == "en" else \
               (f"Main samajh rahi hoon. Gap sirf {gap_hi} ka hai, aur staged payments aur plot loan se bahut se buyers ise "
                "aaraam se manage karte hain. Koi obligation nahi: kya Property Expert ke saath das minute ki call theek rahegi?")
    return (f"Understood, many of our buyers started near {amount}. Entry plots begin at ninety-two point four lakh, but "
            "payments are staged with construction till 2029 and our expert can arrange plot loans to keep the monthly outgo light, "
            "in a fast-growing airport corridor. Shall I have our expert show you a payment plan around your budget?") if lang == "en" else \
           (f"Samajh gayi, kaafi buyers ne {amount} ke aas-paas se shuru kiya tha. Entry plots ninety-two point four lakh se shuru "
            "hote hain, par payments 2029 tak construction ke saath staged hain aur expert plot loan arrange kar sakte hain, "
            "taaki monthly outgo halka rahe. Kya expert aapke budget ke hisaab se payment plan dikhayen?")


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


SLOT = re.compile(
    r"\b((today|tomorrow|kal|parso|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"(\s+(morning|evening|afternoon|night|subah|shaam|dopahar|raat))?"
    r"(\s+((?:at|around|by|about|after|before)\s+)*\d{1,2}(:\d{2})?\s*(am|pm|a\.m\.|p\.m\.|baje)?)?"
    r"(\s+(saat|aath|nau|das|gyarah|barah|ek|do|teen|chaar|paanch|chhe)\s+baje)?)", re.I)


def _complete_slot(slot: str, said: str) -> str:
    """Say the time back exactly: "Tomorrow around of 1PM" -> "tomorrow at 1 pm" (the time must never be dropped)."""
    t = re.search(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?)", said, re.I)
    if t and not re.search(r"\d", slot):
        mins = f":{t.group(2)}" if t.group(2) and t.group(2) != "00" else ""
        slot = f"{slot} at {t.group(1)}{mins} {t.group(3).replace('.', '').lower()}"
    elif not re.search(r"\d", slot):
        part = re.search(r"\b(morning|afternoon|evening|night|subah|dopahar|shaam|raat)\b", said, re.I)
        if part and part.group(1).lower() not in slot.lower():
            slot = f"{slot} {part.group(1).lower()}"
    slot = re.sub(r"\b(Around|At|By|About|After|Before)\b", lambda x: x.group(1).lower(), slot)
    return re.sub(r"^(Tomorrow|Today)\b", lambda x: x.group(1).lower(), slot)


_CLOCK = re.compile(r"\b\d{1,2}([:.]\d{2})?\s*(am|pm|a\.m\.|p\.m\.|baje|o'?clock)\b|\b(morning|afternoon|evening|night|noon|subah|dopahar|shaam|raat)\b", re.I)
_TIME_FOLLOWUP = re.compile(r"^Sure, (.+?)\. What time would suit you", re.I)
_TIME_FOLLOWUP_HI = re.compile(r"^Theek hai, (.+?)\. Kis time", re.I)


def time_followup(messages: list[dict], lang: str) -> str | None:
    """The lead named a DAY for the expert call but no time ("Tomorrow at around…" — the phone cut the rest):
    ask for the time once instead of confirming without it."""
    last = messages[-1]["text"] if messages and messages[-1]["role"] == "user" else ""
    if re.search(r"call (me )?back|busy|meeting|abhi nahi|not now|later", last.lower()) or _CLOCK.search(last):
        return None
    m = SLOT.search(last)
    prev = next((x["text"] for x in reversed(messages[:-1]) if x["role"] == "assistant"), "")
    if not m or not ("expert" in prev.lower() and re.search(r"day|time|kab|din", prev.lower())):
        return None
    if _TIME_FOLLOWUP.search(prev) or _TIME_FOLLOWUP_HI.search(prev):
        return None   # already asked once: confirm the day as it is
    day = re.sub(r"\s+", " ", m.group(2)).strip().lower()
    day = day.capitalize() if day not in ("tomorrow", "today", "kal", "parso") else day
    return (f"Sure, {day}. What time would suit you for the call?" if lang == "en"
            else f"Theek hai, {day}. Kis time par call theek rahegi?")


def slot_confirmation(messages: list[dict], lang: str) -> str | None:
    """The lead gave a day/time for the Property Expert call → confirm exactly what they said and close politely.
    Not for "call me back later" requests (that's the busy flow)."""
    last = messages[-1]["text"] if messages and messages[-1]["role"] == "user" else ""
    low = last.lower()
    if re.search(r"call (me )?back|busy|meeting|abhi nahi|not now|later", low):
        return None
    prev_raw = next((x["text"] for x in reversed(messages[:-1]) if x["role"] == "assistant"), "")
    follow = _TIME_FOLLOWUP.search(prev_raw) or _TIME_FOLLOWUP_HI.search(prev_raw)
    if follow and not SLOT.search(last) and "?" not in last:
        # Answer to "Sure, tomorrow. What time would suit you?": "4 pm" -> day + time; "any time" -> the day as given.
        last = f"{follow.group(1)} at {last.strip()}" if re.match(r"\s*\d", last) else             (f"{follow.group(1)} {last}" if _CLOCK.search(last) else follow.group(1))
        low = last.lower() + " expert"
    m = SLOT.search(last)
    if not m:
        return None
    prev = prev_raw.lower()
    # "Sure, tomorrow. What time would suit you?" is the expert-call question too (it just doesn't say "expert")
    asked_slot = (re.search(r"(day|time|kab|kaunsa din|when)", prev) and "expert" in prev) or bool(follow)
    has_time = bool(m.group(3) or m.group(5) or m.group(9))   # a day AND a time = an appointment
    if not ("expert" in low or asked_slot or has_time):
        return None
    slot = re.sub(r"\s+", " ", m.group(1)).strip()
    slot = _complete_slot(slot, last)
    pitch = "pitch" in covered(messages)
    if lang == "en":
        extra = "" if pitch else ("They'll walk you through our private valley with seventy-four percent open green space, "
                                  "eco-parks and the twenty thousand square foot clubhouse. ")
        return f"Perfect, I have noted {slot} for your call with our Property Expert. {extra}Thank you, and have a lovely day!"
    extra = "" if pitch else ("Woh aapko seventy-four percent open green space, eco-parks aur twenty thousand square foot "
                              "clubhouse wali hamari private valley ke baare mein batayenge. ")
    return f"Perfect, maine {slot} Property Expert ki call ke liye note kar liya hai. {extra}Dhanyavaad, aapka din shubh ho!"


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
    nxt = next_question(messages, lang)
    if nxt.startswith(("No problem", "Koi baat nahi")):
        return nxt   # a polite close carries its own opener
    turn = sum(1 for m in messages if m["role"] == "user")
    opener = (["Perfect.", "Got it.", "Great.", "Understood."] if lang == "en" else ["Theek hai.", "Samajh gayi.", "Bahut badhiya."])
    return f"{opener[turn % len(opener)]} {nxt}"


# ── guardrails applied to every LLM reply ───────────────────────────────────
DAYS = r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow)\b"
TIMES = r"\b\d{1,2}(:\d{2})?\s?(am|pm|a\.m\.|p\.m\.|baje)\b"


REFUSAL = re.compile(r"\b(i('| a)?m sorry, (but )?i can('|no)t help|i can('|no)t (help|assist) with)", re.I)


def keep_language(reply: str, lang: str) -> str:
    """A Hinglish speaker must not get the English script question: swap it for the Hindi version."""
    if lang != "hi" or re.search(HINDI, reply.lower()):
        return reply
    for q in _questions().values():
        if q.get("en") and q["en"] in reply and q.get("hi"):
            return reply.replace(q["en"], q["hi"])
    return reply


def no_reask(reply: str, messages: list[dict], lang: str) -> str:
    """PDF: "avoid re-asking questions if the user provides info early". Drop any question in the reply about a
    checkpoint the lead has already answered; respond() then adds the next unanswered one."""
    done = covered(messages)
    sentences = re.split(r"(?<=[.!?])\s+", reply.strip())
    after_pitch = "pitch" in done and "callback" not in done
    keep = [x for x in sentences if not (x.endswith("?") and (any(
        step in done and re.search(ASKED[step], x.lower()) for step in ("intent", "geography", "budget", "timeline", "decision"))
        or (after_pitch and re.search(r"anything else|aur kuch", x.lower()))))]   # after the pitch: ask for the time instead
    return " ".join(keep) if keep else reply


def guard(reply: str, messages: list[dict], lang: str) -> str:
    """Fix the two failure modes the evaluation found: invented slots and a skipped pitch."""
    lead = " ".join(m["text"].lower() for m in messages if m["role"] == "user")
    if REFUSAL.search(reply):   # a sales consultant never says "I can't help with that"
        reply = ("Understood. This is a plotted community with possession in December 2029, so it suits buyers who can plan "
                 "ahead; our Property Expert can also guide you on what fits you best. Would a short call with them help?"
                 if lang == "en" else
                 "Samajh gayi. Yeh plotted community hai, possession December 2029 tak, toh yeh aage ki planning wale buyers ke "
                 "liye hai; hamare Property Expert aapko sahi option batayenge. Kya unke saath ek short call theek rahegi?")
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
        r = _questions()["pitch"][lang] if "pitch" not in covered(messages) else \
            ("What day and time would suit a short call with our Property Expert?" if lang == "en"
             else "Hamare Property Expert ke saath call ke liye kaunsa din aur time theek rahega?")
    elif asks_expert and not lead_gave_slot and "pitch" not in covered(messages + [{"role": "assistant", "text": r}]):
        # The PDF requires the pitch before the CTA.
        r = _questions()["pitch"][lang]
    return r


# ── Questions answered by a live web search (places and things that are not in the fact list) ──────
# "How far is BTM Layout?", "Any malls nearby?", "Is there a metro?" -> Divya says "Let me quickly check"
# and Groq searches the web. Airport / Nandi Hills / STRR / railway / Yelahanka distances are already facts.
AREAS = ["btm layout", "btm", "koramangala", "hsr layout", "hsr", "indiranagar", "whitefield", "electronic city",
         "mg road", "majestic", "hebbal", "yelahanka", "jayanagar", "jp nagar", "marathahalli", "manyata",
         "rt nagar", "malleshwaram", "banashankari", "bellandur", "sarjapur", "kr puram", "yeshwanthpur",
         "devanahalli", "chikkaballapur", "chikballapur", "doddaballapura", "doddaballapur", "hoskote", "tumkur", "mysore", "hosur", "chennai",
         "rajajinagar", "basavanagudi", "ulsoor", "frazer town", "kalyan nagar", "hennur", "thanisandra",
         "jakkur", "sahakar nagar", "vidyaranyapura", "peenya", "nelamangala", "bannerghatta", "city centre",
         "city center", "bangalore city", "bengaluru city", "cubbon park", "vidhana soudha", "kia", "embassy"]
KNOWN_PLACES = r"\b(airport|kia|kempegowda|nandi|foothills?|strr|ring road|railway|train station|yelahanka|project|site|plot)\b"
WEB_TOPICS = {
    "malls": r"\b(malls?|shopping|multiplex|cinemas?|movie theat(re|er)s?|pvr|inox)\b",
    "restaurants": r"\b(restaurants?|cafes?|eateries|food court|dhabas?)\b",
    "hotels": r"\b(hotels?|resorts?)\b",
    "metro": r"\b(metro)\b",
    "bus": r"\b(bus|buses|bus stand|bus stop)\b",
    "worship": r"\b(temples?|church(es)?|mosques?|masjid|mandir|gurudwara)\b",
    "shops": r"\b(supermarkets?|grocery|groceries|d ?mart|petrol (pump|bunk)s?|atms?|pharmac(y|ies)|medical shops?)\b",
    "work": r"\b(tech parks?|it parks?|it hub|aerospace park|sez|foxconn|offices nearby)\b",
    "leisure": r"\b(golf|lakes?|trek\w*|wineries|vineyards?|tourist|picnic|waterfalls?)\b",
    "weather": r"\b(weather|temperature|climate|rain(fall)?)\b",
    "growth": r"\b(development plans?|upcoming (projects?|infrastructure)|news)\b",
}
DISTANCE = r"\b(how far|distance|kitni door|kitna door|kitna dur|kitni dur|travel time|commute|how long (does|will|would) it take|drive (from|to))\b"


def needs_search(utterance: str) -> dict | None:
    """A question about the area that the fact list can't answer -> {"q": what to search, "key": cache key}."""
    u = " " + re.sub(r"[^a-z0-9 ?']", " ", (utterance or "").lower()) + " "
    if not (re.search(QUESTION, u) or "?" in (utterance or "")):
        return None
    if re.search(r"\b(price|cost|emi|loan|discount|returns?|roi)\b", u) and not re.search(DISTANCE, u):
        return None   # money questions: facts / the Property Expert, never the web
    places = [a for a in AREAS if re.search(rf"\b{re.escape(a)}\b", u)]
    places = [p for p in places if not any(p != o and p in o for o in places)]   # "btm" inside "btm layout"
    topics = [t for t, pat in WEB_TOPICS.items() if re.search(pat, u)]
    if re.search(DISTANCE, u) and not places:
        m = re.search(r"\b(?:from|to|till|se)\s+(?:the\s+|my\s+)?([a-z][a-z ]{2,30}?)(?=\s*(?:\?|$| is| se| and| from| to| for| by))", u)
        place = (m.group(1).strip() if m else "")
        # Not a place: question words, or topics the facts already answer ("schools, colleges, and how far").
        not_place = r"\b(how|far|what|which|where|here|there|it|this|that|you|me|nearest|school|schools|college|colleges|" \
                    r"hospitals?|clinics?|amenit\w*|club\w*|price|plots?|possession)\b"
        if place and not re.search(KNOWN_PLACES, place) and not re.search(not_place, place):
            places = [place]
    places = [p for p in places if not re.search(KNOWN_PLACES, p)]
    if not places and not topics:
        return None
    key = "|".join(sorted(f"to:{p}" for p in places) + sorted(topics))
    return {"q": (utterance or "").strip()[:200], "key": key}


# "How far is Nandi Hills?" asks about ONE place: answer just that one, not the whole location list.
ONE_PLACE = [
    (r"\bnandi\b", "Nandi Hills foothills are just about fifteen minutes from the project.",
     "Nandi Hills foothills project se sirf pandrah minute door hain."),
    (r"\b(airport|kia|kempegowda)\b", "Kempegowda International Airport is about thirty to thirty-five minutes away.",
     "Kempegowda International Airport lagbhag tees se paintees minute door hai."),
    (r"\b(railway|train)\b", "Doddaballapura railway station is about twelve minutes away.",
     "Doddaballapura railway station lagbhag barah minute door hai."),
    (r"\b(strr|ring road|expressway)\b", "The STRR expressway corridor is about ten minutes away.",
     "STRR expressway corridor lagbhag das minute door hai."),
    (r"\byelahanka\b", "Yelahanka city centre is about thirty-five minutes away.",
     "Yelahanka city centre lagbhag paintees minute door hai."),
    (r"\bindustrial\b", "The Doddaballapura Industrial Hub is about fifteen minutes away.",
     "Doddaballapura Industrial Hub lagbhag pandrah minute door hai."),
]


def one_place(utterance: str, lang: str) -> str | None:
    """Short answer when the lead asks how far ONE known place is; None for general location questions."""
    u = (utterance or "").lower()
    if not re.search(DISTANCE + r"|\b(near|close|minutes?|kitna time)\b", u):
        return None
    hits = [(en, hi) for pat, en, hi in ONE_PLACE if re.search(pat, u)]
    if not hits or len(hits) > 2:
        return None
    return " ".join(h[0] if lang == "en" else h[1] for h in hits)
