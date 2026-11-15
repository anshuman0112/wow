"""Aanya on a REAL phone call using only a free Twilio trial.

Twilio's trial won't bridge calls into Vapi, but it does allow its own speech recognition
(<Gather input="speech">) and voices (<Say>). So the conversation loop runs here:

    lead's phone ── Twilio hears them (speech → text) ──► /api/phone/turn
                                                         │  same Aanya system prompt + Groq LLM
    lead's phone ◄── Twilio speaks the reply (Polly Kajal, Indian English/Hindi) ◄┘

Conversation state lives in the `calls` row (vapi_call_id = "tw_<CallSid>"), so it works on
serverless. When the call ends we run the same AI analysis as Vapi calls and update the lead.
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote
from xml.sax.saxutils import escape

import httpx

from . import cache, faq
from .calls import apply_lead_update
from .campaign import LEAD_ANALYSIS_OUTPUT
from .clients import Groq, Supabase, telegram_alert
from .settings import settings

def phone_voice() -> str:
    """Voice for phone calls: PHONE_VOICE env, else the campaign's default from its voice library."""
    import os
    from .campaign import data
    return os.environ.get("PHONE_VOICE", "").strip() or data()["phoneVoices"]["default"]


VOICE = phone_voice()   # premium Indian-English voice (Google Chirp3-HD / Amazon generative), see campaign.json
MAX_TURNS = 14                     # keeps calls ~3 minutes and protects free quotas
# Words Twilio's speech recognition should expect (improves "70 lakh" vs "7260 lacs").
HINTS = ("lakh, lakhs, crore, seventy lakh, one crore, Nandi Hills, Devanahalli, Divyasree, Whispers of the Wind, "
         "investment, weekend home, self use, budget, amenities, clubhouse, schools, hospitals, airport, possession, "
         "December 2029, Property Expert, Saturday, Sunday, Monday, morning, evening, haan, nahi, theek hai")

def compact_prompt() -> str:
    """Same rules, flow, facts and edge cases as the full prompt, ~1/3 the tokens.
    Free Groq allows ~8k tokens/minute per model, so a smaller prompt keeps the best model for the whole call."""
    from .campaign import data
    d = data()
    facts = "; ".join(f"{f['k']}: {f['v']}{' (approx.)' if f['src'] == 'web' else ''}" for g in d["facts"] for f in g["items"])
    return f"""You are Aanya, a Divyasree Developers consultant on an outbound call about Whispers of the Wind, premium "Private Valley" villa plots near Nandi Hills, North Bengaluru. Tone: premium, warm, never pushy. Goal: qualify on 4 checkpoints, short pitch, book a Property Expert call, in 2-3 minutes.

RULE 1 — ANSWER QUESTIONS FIRST: if the lead asks anything (price, budget range, amenities, clubhouse, location, distances, nearby schools/hospitals, possession, RERA…), answer it directly in one sentence using FACTS, then ask ONE next question from the flow. Never ignore a question and never push the expert call while the lead is still asking about the property.
RULE 2 — NEVER INVENT: only state FACTS below. Price range is ninety-two point four lakh to two point four six crore incl. taxes — say it whenever price or budget is asked. For things not in FACTS (exact plot price, EMI, discounts, schools' fees, other projects) say our Property Expert will confirm. NEVER propose a day or time yourself — always ASK the lead what day and time suits them.
RULE 3 — STYLE: max 2 short sentences; one question per turn; varied affirmation (Understood / Perfect / Got it); never re-ask what the lead already told you; money in words; admit you are Divyasree's AI assistant if asked; after two refusals or "don't call", apologise and end.
RULE 4 — UNCLEAR SPEECH: phone transcription can be wrong (e.g. "7260 lacs" probably means "70 lakh"). If a number or answer looks odd, confirm it briefly ("Just to confirm, about seventy lakh?").

FLOW (skip answered steps; only move on when the lead has no open question): 1) Intent: weekend home or investment? 2) Geography: comfortable with Nandi Hills/Devanahalli near the airport corridor? 3) Budget: plots start at ninety-two point four lakh incl. taxes, does that work? 4) Timeline: phased delivery, possession December 2029, comfortable? 5) PITCH (required, never skip): in the same turn as step 6, first paint the picture in one sentence: "a private valley with 74% open green space, eco-parks, Nandi Hills views and a 20,000 sq ft clubhouse, among a like-minded community". 6) Then ask what day and time suits them for a short Property Expert call (let THEM choose), and confirm it back. 7) Thank them and end.

OBJECTIONS (be persuasive but truthful: up to two warm, benefit-led counters, then accept gracefully): location far -> weekend escape, ~30 min to the airport, 10 min to STRR, fast-growing airport/STRR corridor = strong future exposure; budget low -> staged construction-linked payments (not all upfront), the expert arranges plot-loan options to keep the monthly outgo light, early entry into a growth corridor, the gap is small; NEVER quote an EMI amount, discount or guaranteed return; busy -> ask a better time and end; irritated -> apologise once, keep it very short or offer a callback; angry/"don't call" -> apologise, end.

LANGUAGE: start in English; if the lead speaks Hindi/Hinglish, reply in simple Hinglish (English letters only).

FACTS: {facts}"""


PHONE_RULES = """

# PHONE MODE (this call runs over a plain phone line)
You cannot use tools. Reply ONLY with JSON: {"reply": "<what you say next>", "end": true|false, "lang": "en"|"hi"}
- "reply": 1–2 short spoken sentences, English letters only (Hinglish is fine), no symbols or lists.
- "end": true only when the call should finish (callback booked and confirmed, lead declined twice,
  asked not to be called, wrong person, or already said goodbye). Your reply is then the goodbye line.
- "lang": "hi" if the lead is speaking Hindi/Hinglish, otherwise "en".
- If the lead's words look garbled or empty, politely ask them to repeat.
"""


SYSTEM_PHONE = compact_prompt() + PHONE_RULES   # built once per process; identical on every request


def _sid_key(call_sid: str) -> str:
    return f"tw_{call_sid}"


def _first_name(name: str | None) -> str:
    return (name or "").strip().split(" ")[0] if name else ""


def greeting(name: str | None) -> str:
    who = _first_name(name) or "there"
    return (f"Hello {who}! This is Aanya, a consultant from Divyasree Developers, calling about Whispers of the Wind, "
            "our villa plot community near Nandi Hills in North Bengaluru. Is this a good time for two minutes?")


def twiml_gather(say: str, lead_id: str, lang: str = "en", voice: str | None = None) -> str:
    base = settings().public_base_url
    action = escape(f"{base}/api/phone/turn?lead={quote(lead_id)}")
    silence = escape(f"{base}/api/phone/turn?lead={quote(lead_id)}&silence=1")
    language = "hi-IN" if lang == "hi" else "en-IN"
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'<Gather input="speech" action="{action}" method="POST" language="{language}" '
            f'speechTimeout="auto" timeout="6" bargeIn="true" hints="{escape(HINTS)}" actionOnEmptyResult="false">'
            f'{says(say, voice)}</Gather>'
            f'<Redirect method="POST">{silence}</Redirect></Response>')


def twiml_goodbye(say: str, voice: str | None = None) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'{says(say, voice)}<Hangup/></Response>')


def says(text: str, voice: str | None = None) -> str:
    """One <Say> per sentence: Twilio voices each block separately, so the first words play sooner
    (one long block must be fully synthesised before the lead hears anything)."""
    from .campaign import data
    for term, sound in data().get("phoneSayAs", []):   # pronunciation guide (e.g. Divyasree → Divya shree)
        text = re.sub(rf"\b{re.escape(term)}\b", sound, text)
    parts = [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p] or [text]
    v = voice or VOICE
    return "".join(f'<Say voice="{escape(v)}" language="en-IN">{escape(p)}</Say>' for p in parts)


async def _load(sb: Supabase, call_sid: str) -> dict | None:
    rows = await sb.select("calls", {"select": "vapi_call_id,lead_id,name,messages,raw,started_at,summary",
                                     "vapi_call_id": f"eq.{_sid_key(call_sid)}"})
    return rows[0] if rows else None


async def load_session(http: httpx.AsyncClient, sb: Supabase, call_sid: str) -> dict | None:
    """Redis first (fast, during the call); Supabase as fallback / source of truth."""
    return await cache.get_session(http, call_sid) or await _load(sb, call_sid)


async def save_session(http: httpx.AsyncClient, sb: Supabase, call_sid: str, row: dict) -> None:
    if not await cache.set_session(http, call_sid, row):
        await sb.update("calls", {"vapi_call_id": f"eq.{_sid_key(call_sid)}"},
                        {"messages": row.get("messages"), "raw": row.get("raw")})


async def start(http: httpx.AsyncClient, call_sid: str, lead_id: str, to_number: str | None) -> str:
    """First request when the lead answers: create the session row and greet them."""
    sb = Supabase(http)
    lead = (await cache.get_lead(http, lead_id)) or {}   # stashed by "Call now" → no database trip
    if lead_id and not lead:
        rows = await sb.select("leads", {"select": "id,name,phone,location", "id": f"eq.{lead_id}"})
        lead = rows[0] if rows else {}
    hello = greeting(lead.get("name"))
    from . import voices
    voice = lead.get("voice") or await voices.selected(http)   # chosen in the dashboard
    row = {
        "vapi_call_id": _sid_key(call_sid), "lead_id": lead.get("id"), "name": lead.get("name"),
        "phone": lead.get("phone") or to_number, "call_type": "twilioPhoneCall",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "messages": [{"role": "assistant", "text": hello}],
        "raw": {"engine": "twilio-gather", "voice": voice, "silences": 0, "lang": "en", "location": lead.get("location"),
                "session_store": "redis" if cache.fast_enough() else "supabase"},
    }
    # Fast path: the call lives in Redis and is written to Supabase after hang-up (status callback).
    if not await cache.set_session(http, call_sid, row):
        await sb.upsert("calls", row, "vapi_call_id")
    return twiml_gather(hello, lead.get("id") or "", voice=voice)


async def turn(http: httpx.AsyncClient, call_sid: str, lead_id: str, speech: str, silence: bool) -> str:
    sb, groq = Supabase(http), Groq(http)
    row = await load_session(http, sb, call_sid)
    if row is None:  # Twilio called /turn first (shouldn't happen) — start fresh
        return await start(http, call_sid, lead_id, None)
    messages = row.setdefault("messages", [])
    raw = row.setdefault("raw", {})

    if silence or not speech.strip():
        raw["silences"] = raw.get("silences", 0) + 1
        if raw["silences"] >= 2:
            bye = "I'll try you another time. Thank you, and have a lovely day!"
            messages.append({"role": "assistant", "text": bye})
            raw["ended_reason"] = "silence-timed-out"
            await save_session(http, sb, call_sid, row)
            if not cache.fast_enough():
                await finish(http, call_sid, ended_reason="silence-timed-out")
            return twiml_goodbye(bye, raw.get("voice"))   # with Redis, Twilio's hang-up callback saves + analyses the call
        await save_session(http, sb, call_sid, row)
        return twiml_gather("Are you still there?", row.get("lead_id") or lead_id, raw.get("lang", "en"), raw.get("voice"))

    if TRIAL_NOISE.search(speech) and len(messages) <= 1:
        await save_session(http, sb, call_sid, row)
        return twiml_gather("Sorry about that. As I was saying, is this a good time for two minutes?",
                            row.get("lead_id") or lead_id, raw.get("lang", "en"), raw.get("voice"))
    messages.append({"role": "user", "text": speech.strip()})
    out = await respond(groq, messages, row.get("name"), raw.get("location"), raw.get("lang", "en"))
    reply = (out.get("reply") or "Sorry, could you say that once more?").strip()[:600]
    end = bool(out.get("end")) or len(messages) >= MAX_TURNS * 2
    raw.update({"lang": out.get("lang", raw.get("lang", "en")), "silences": 0})
    raw.setdefault("usage", []).append(out.get("_usage"))     # per-turn tokens/latency for evaluation
    messages.append({"role": "assistant", "text": reply})
    if end:
        raw["ended_reason"] = "assistant-ended-call"
    await save_session(http, sb, call_sid, row)
    if end:
        if not cache.fast_enough():
            await finish(http, call_sid, ended_reason="assistant-ended-call")
        return twiml_goodbye(reply, raw.get("voice"))   # goodbye plays immediately; analysis happens after hang-up
    return twiml_gather(reply, row.get("lead_id") or lead_id, raw["lang"], raw.get("voice"))


_SPOKEN = str.maketrans({"’": "'", "‘": "'", "“": "", "”": "", "‑": "-", "‐": "-",
                         "–": " to ", "—": ", ", " ": " ", " ": " ", "×": " by ", "&": " and ",
                         "%": " percent", "₹": "rupees ", "*": "", "#": "", "…": "."})


def speakable(text: str) -> str:
    """Plain English letters only: phones read odd symbols (‑ × ’ ₹) aloud as garbage."""
    t = text.translate(_SPOKEN).encode("ascii", "ignore").decode()
    return re.sub(r"\s{2,}", " ", t).strip()


# Twilio's trial announcement is sometimes transcribed as the lead's first words — it isn't them.
TRIAL_NOISE = re.compile(r"no longer being recorded|trial account|press any key|free trial|twilio", re.I)

REPLY_BUDGET_S = 3.0   # max time we let the AI think on a live call before falling back
HISTORY_WINDOW = 12   # last ~6 exchanges: enough context, bounded token cost on long calls


def build_chat(messages: list[dict], name: str | None, location: str | None, lang: str = "en") -> list[dict]:
    """Cache-friendly order: the big system prompt is byte-identical on every turn of every call
    (so the provider can reuse its cached prefix); per-lead details come last, then a bounded history."""
    hist = messages[-HISTORY_WINDOW:]
    if hist and hist[0]["role"] == "user" and messages and messages[0]["role"] == "assistant" and len(messages) > len(hist):
        hist = [messages[0]] + hist   # always keep the greeting so the model knows the call opened
    return ([{"role": "system", "content": SYSTEM_PHONE}] +
            [{"role": "user" if m["role"] == "user" else "assistant", "content": m["text"]} for m in hist] +
            [{"role": "system", "content": f"Lead name: {name or 'unknown'}. Lead location: {location or 'unknown'}. "
                                         + ("The lead speaks Hindi/Hinglish: reply in simple Hinglish (English letters), lang=hi. " if lang == "hi" else "")
                                         + "Reply with the JSON object only."}])


async def think(groq: Groq, messages: list[dict], name: str | None = None, location: str | None = None, lang: str = "en") -> dict:
    """LLM step: history in → {"reply", "end", "lang"} out (one retry if the reply comes back empty)."""
    t0 = time.perf_counter()
    out: dict = {}

    async def attempt() -> dict:
        for _ in range(2):
            try:
                r = await groq.chat_json(build_chat(messages, name, location, lang))
            except Exception:  # noqa: BLE001
                r = {}
            if (r.get("reply") or "").strip():
                return r
        return {}

    try:
        # Hard budget for a live call: if the AI can't answer in time, respond() falls back to the
        # script + facts instantly instead of leaving the caller in silence.
        out = await asyncio.wait_for(attempt(), timeout=REPLY_BUDGET_S)
    except asyncio.TimeoutError:
        out = {}
        groq.last_usage = {"model": "timeout", "budget_s": REPLY_BUDGET_S}
    out["_latency_s"] = round(time.perf_counter() - t0, 2)
    out["_usage"] = groq.last_usage
    return out


async def respond(groq: Groq, messages: list[dict], name: str | None, location: str | None, lang: str) -> dict:
    """One conversational step for live calls AND the evaluator.

    1. Plain property question → answer from facts via the Redis FAQ cache (0 tokens) + next script question.
    2. Anything else → LLM, then code guardrails (no invented slots, pitch before the CTA).
    """
    speech = messages[-1]["text"] if messages and messages[-1]["role"] == "user" else ""
    lang = faq.lang_of(speech, lang)
    intents = faq.detect(speech)
    t0 = time.perf_counter()
    objection = faq.budget_objection(messages, lang) or faq.location_objection(messages, lang)
    if objection:   # objections first: "it's too far from my office" must be countered, not answered as a FAQ
        low = objection.lower()
        out = {"reply": objection, "end": "have a lovely day" in low or "din shubh" in low, "lang": lang,
               "_latency_s": round(time.perf_counter() - t0, 3),
               "_usage": {"model": "rule:objection", "prompt_tokens": 0, "completion_tokens": 0}}
    elif intents:
        http = groq.http
        cached = {}
        for i in intents:
            hit = await cache.get_faq(http, i, lang)
            if hit:
                cached[i] = hit
            else:
                await cache.set_faq(http, i, lang, faq.answer([i], lang))   # warm the cache
        await cache.count_faq(http, intents)
        reply = f"{faq.answer(intents, lang, cached)} {faq.next_question(messages, lang)}"
        out = {"reply": reply, "end": False, "lang": lang, "_latency_s": round(time.perf_counter() - t0, 3),
               "_usage": {"model": "faq-cache" + ("+redis" if cache.fast_enough() else ""), "prompt_tokens": 0,
                          "completion_tokens": 0, "intents": intents, "redis_hits": len(cached)}}
    else:
        out = await think(groq, messages, name, location, lang)
        if out.get("reply"):
            out["reply"] = faq.guard(out["reply"], messages, out.get("lang") or lang)
        else:   # every model rate-limited/failed: answer from the script instead of "say that once more"
            out.update({"reply": faq.fallback_reply(messages, lang), "end": False, "lang": lang,
                        "_usage": {"model": "rule:fallback", "prompt_tokens": 0, "completion_tokens": 0}})
    reply = speakable(out.get("reply") or "")
    if reply and "?" not in reply and not out.get("end"):
        reply = f"{reply} {faq.next_question(messages + [{'role': 'assistant', 'text': reply}], out.get('lang') or lang)}"
    out["reply"] = reply   # never leave the lead in dead air: every turn ends with the next question
    print(f"[phone] {out.get('_usage')} latency_s={out.get('_latency_s')}", flush=True)
    return out


async def finish(http: httpx.AsyncClient, call_sid: str, ended_reason: str = "customer-ended-call",
                 duration: float | None = None) -> dict:
    """Analyse the conversation (same schema as Vapi calls), save it and update the lead. Idempotent."""
    sb, groq = Supabase(http), Groq(http)
    live = await cache.get_session(http, call_sid)          # fast path: the call lived in Redis
    saved = await _load(sb, call_sid)
    if saved and saved.get("summary"):  # already analysed
        if duration:
            await sb.update("calls", {"vapi_call_id": f"eq.{_sid_key(call_sid)}"}, {"duration_sec": duration})
        return {"finished": True, "already": True}
    row = live or saved
    if row is None:
        return {"finished": False}
    ended_reason = (row.get("raw") or {}).get("ended_reason") or ended_reason
    if not saved:   # first write of this call to Supabase
        await sb.upsert("calls", {k: row.get(k) for k in ("vapi_call_id", "lead_id", "name", "phone", "call_type", "started_at")},
                        "vapi_call_id")

    messages = row.get("messages") or []
    transcript = "\n".join(("Lead: " if m["role"] == "user" else "Aanya: ") + m["text"] for m in messages)
    props = LEAD_ANALYSIS_OUTPUT["schema"]["properties"]
    schema_desc = "\n".join(f"- {k}: {v.get('description', '')}{' One of ' + str(v['enum']) if 'enum' in v else ''}" for k, v in props.items())
    try:
        q = await groq.chat_json([
            {"role": "system", "content": "You analyse a real-estate sales call transcript. Reply with JSON only, with these fields:\n" + schema_desc},
            {"role": "user", "content": transcript or "(no conversation)"}], max_tokens=900)
    except Exception:  # noqa: BLE001
        q = {}
    ended = datetime.now(timezone.utc)
    started = row.get("started_at")
    if duration is None and started:
        duration = (ended - datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds()
    update = {
        "ended_at": ended.isoformat(), "duration_sec": duration, "ended_reason": ended_reason,
        "transcript": transcript, "ai_lines": "\n".join(m["text"] for m in messages if m["role"] == "assistant"),
        "summary": q.get("summary") or "Phone call (no summary available).",
        "interest": q.get("interest") if q.get("interest") in ("hot", "warm", "cold") else None,
        "intent": q.get("intent"), "geography_fit": q.get("geography_fit"), "budget_fit": q.get("budget_fit"),
        "timeline_fit": q.get("timeline_fit"), "sentiment_start": q.get("sentiment_start"),
        "sentiment_end": q.get("sentiment_end"), "language": q.get("language"),
        "callback_time": q.get("callback_time") or None, "do_not_call": q.get("do_not_call") is True,
        "analysis": q, "cost_usd": 0,
        "messages": messages, "raw": row.get("raw"),
    }
    update = {k: v for k, v in update.items() if v is not None}
    await sb.update("calls", {"vapi_call_id": f"eq.{_sid_key(call_sid)}"}, update)
    status = await apply_lead_update(sb, {**update, "lead_id": row.get("lead_id")})
    if update.get("interest") == "hot":
        await telegram_alert(http, f"🔥 Hot lead (phone): {row.get('name') or 'Caller'}\n{update['summary']}")
    return {"finished": True, "interest": update.get("interest"), "lead_status": status}
