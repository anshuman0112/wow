"""Divya on a REAL phone call using only a free Twilio trial.

Twilio's trial won't bridge calls into Vapi, but it does allow its own speech recognition
(<Gather input="speech">) and voices (<Say>). So the conversation loop runs here:

    lead's phone ── Twilio hears them (speech → text) ──► /api/phone/turn
                                                         │  same Divya system prompt + Groq LLM
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
from . import scoring
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
    from . import config_store
    from .campaign import data
    d = data()
    q = config_store.questions()
    # Facts trimmed for the phone: approximate figures are flagged once ("~"), not per line.
    facts = "; ".join(f"{f['k']}: {_short_fact(f['v'])}" for g in d["facts"] for f in g["items"])
    # Kept short on purpose: every token counts against the free 8k-tokens/minute Groq limit, and hitting
    # that limit is what made slow phone turns (model switches + timeouts). Objections, FAQs, slot
    # confirmation and the next checkpoint are also enforced in code (faq.py), so the prompt stays lean.
    return f"""You are Divya, Divyasree Developers' consultant, on an outbound call about Whispers of the Wind: premium "Private Valley" villa plots near Nandi Hills, North Bengaluru. Premium, warm, never pushy. Goal in 2-3 min: 4 checkpoints, short pitch, book a Property Expert call.

RULES
1. Lead asks something -> answer in one sentence from FACTS, then ask ONE next FLOW question. Never ignore a question.
2. Never invent. Price: ninety-two point four lakh to two point four six crore incl. taxes. Not in FACTS (exact plot price, EMI, discounts, returns) -> the Property Expert will confirm. NEVER propose a day/time; ask the lead.
3. Max 2 short sentences, one question per turn, vary affirmations (Understood / Perfect / Got it), never re-ask what they told you, money in words. If asked, you are Divyasree's AI assistant.
4. Transcripts can be wrong ("7260 lacs" = "70 lakh"): confirm odd numbers briefly.

FLOW (skip answered steps): 1 Intent: "{q['intent']['en']}" 2 Geography: "{q['geography']['en']}" 3 Budget: "{q['budget']['en']}" 4 Timeline: "{q['timeline']['en']}" 4b Decision (soft, once): "{q['decision']['en']}" 5 PITCH, never skip, same turn as 6: "{q['pitch']['en']}" 6 Let THEM choose the day and time, confirm it back. 7 Thank and end.

OBJECTIONS (up to two warm, truthful counters, then accept): far -> weekend escape, ~30 min to airport, 10 min to STRR, growth corridor; budget -> staged development-linked payments, the expert arranges plot loans for a light monthly outgo, the gap is small (never quote EMI, discount or returns); wants ready/city -> "This is a plotted community with possession in December 2029, so it suits buyers who plan ahead", offer the expert; busy -> (apologise if irritated) ask WHEN to call back, repeat their time back, end (never suggest a time); irritated -> apologise, keep it short; angry, "don't call" or two refusals -> apologise, end.

LANGUAGE: English; if the lead speaks Hindi/Hinglish, reply in simple Hinglish (English letters).

FACTS (~ = approximate): {facts}"""


def _short_fact(v: str) -> str:
    v = re.sub(r"\s*\((?:approx\.?|the Property Expert[^)]*|exact[^)]*)\)", "", str(v))
    return v.replace("approximately", "~").replace(" as listed online", "").strip()


PHONE_RULES = """

PHONE: reply ONLY with JSON {"reply": "...", "end": true|false, "lang": "en"|"hi"}. reply = 1-2 short spoken sentences, English letters only, no symbols. end = true only when finishing (time booked and confirmed, declined twice, don't call, wrong person, goodbye); reply is then the goodbye. lang = "hi" for Hindi/Hinglish. Garbled words -> ask them to repeat.
"""


_SYSTEM: tuple[int, str] | None = None


def system_phone() -> str:
    """The phone prompt: identical on every turn (so the provider can cache it), rebuilt only when Settings change."""
    global _SYSTEM
    from . import config_store
    if _SYSTEM is None or _SYSTEM[0] != config_store.version:
        _SYSTEM = (config_store.version, compact_prompt() + PHONE_RULES)
    return _SYSTEM[1]


def _sid_key(call_sid: str) -> str:
    return f"tw_{call_sid}"


def _first_name(name: str | None) -> str:
    return (name or "").strip().split(" ")[0] if name else ""


def greeting(name: str | None, callback: bool = False) -> str:
    who = _first_name(name) or "there"
    if callback:   # the lead asked us to call back at this time
        return (f"Hello {who}! This is Divya from Divyasree Developers. You had asked me to call you back around now, "
                "about Whispers of the Wind, our villa plot community near Nandi Hills. Is this a good time?")
    return (f"Hello {who}! This is Divya, a consultant from Divyasree Developers, calling about Whispers of the Wind, "
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


async def start(http: httpx.AsyncClient, call_sid: str, lead_id: str, to_number: str | None,
                callback: bool = False) -> str:
    """First request when the lead answers: create the session row and greet them."""
    sb = Supabase(http)
    lead = (await cache.get_lead(http, lead_id)) or {}   # stashed by "Call now" → no database trip
    if lead_id and not lead:
        rows = await sb.select("leads", {"select": "id,name,phone,location", "id": f"eq.{lead_id}"})
        lead = rows[0] if rows else {}
    hello = greeting(lead.get("name"), callback)
    from . import voices
    voice = lead.get("voice") or await voices.selected(http)   # chosen in the dashboard
    row = {
        "vapi_call_id": _sid_key(call_sid), "lead_id": lead.get("id"), "name": lead.get("name"),
        "phone": lead.get("phone") or to_number, "call_type": "twilioPhoneCall",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "messages": [{"role": "assistant", "text": hello}],
        "raw": {"engine": "twilio-gather", "voice": voice, "callback": callback, "silences": 0, "lang": "en", "location": lead.get("location"),
                "session_store": "redis" if cache.fast_enough() else "supabase"},
    }
    # Fast path: the call lives in Redis and is written to Supabase after hang-up (status callback).
    if not await cache.set_session(http, call_sid, row):
        await sb.upsert("calls", row, "vapi_call_id")
    return twiml_gather(hello, lead.get("id") or "", voice=voice)


async def turn(http: httpx.AsyncClient, call_sid: str, lead_id: str, speech: str, silence: bool) -> str:
    t_in = time.perf_counter()
    sb, groq = Supabase(http), Groq(http)
    # Session + the shared Groq quota picture are fetched at the same time (no extra wait).
    row, _ = await asyncio.gather(load_session(http, sb, call_sid), cache.get_quota(http))
    t_loaded = time.perf_counter()
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
    t_replied = time.perf_counter()
    reply = (out.get("reply") or "Sorry, could you say that once more?").strip()[:600]
    end = bool(out.get("end")) or len(messages) >= MAX_TURNS * 2
    raw.update({"lang": out.get("lang", raw.get("lang", "en")), "silences": 0})
    usage = dict(out.get("_usage") or {})
    raw.setdefault("usage", []).append(usage)     # per-turn tokens/latency for evaluation
    messages.append({"role": "assistant", "text": reply})
    if end:
        raw["ended_reason"] = "assistant-ended-call"
    # Timing of this turn on our server (ms), stored with the call. The final session write (~20 ms)
    # can't be inside the record it writes, so the full total is printed to the server log below.
    usage["t_ms"] = {"load": round((t_loaded - t_in) * 1000), "reply": round((t_replied - t_loaded) * 1000),
                     "turn": len(messages) // 2}
    await asyncio.gather(save_session(http, sb, call_sid, row), cache.set_quota(http))
    usage["t_ms"]["server_total"] = round((time.perf_counter() - t_in) * 1000)
    print(f"[latency] call={call_sid[-6:]} turn={usage['t_ms']['turn']} model={usage.get('model')} "
          f"load={usage['t_ms']['load']}ms reply={usage['t_ms']['reply']}ms total={usage['t_ms']['server_total']}ms "
          f"attempts={usage.get('attempts')}", flush=True)
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

REPLY_BUDGET_S = 2.5   # max time we let the AI think on a live call before falling back to the script
REPLY_MAX_TOKENS = 250  # replies are 1-2 sentences (+ a little reasoning); a smaller cap also uses less of the free per-minute quota
HISTORY_WINDOW = 12   # last ~6 exchanges: enough context, bounded token cost on long calls


def build_chat(messages: list[dict], name: str | None, location: str | None, lang: str = "en") -> list[dict]:
    """Cache-friendly order: the big system prompt is byte-identical on every turn of every call
    (so the provider can reuse its cached prefix); per-lead details come last, then a bounded history."""
    hist = messages[-HISTORY_WINDOW:]
    if hist and hist[0]["role"] == "user" and messages and messages[0]["role"] == "assistant" and len(messages) > len(hist):
        hist = [messages[0]] + hist   # always keep the greeting so the model knows the call opened
    return ([{"role": "system", "content": system_phone()}] +
            [{"role": "user" if m["role"] == "user" else "assistant", "content": m["text"]} for m in hist] +
            [{"role": "system", "content": f"Lead name: {name or 'unknown'}. Lead location: {location or 'unknown'}. "
                                         + ("The lead speaks Hindi/Hinglish: reply in simple Hinglish (English letters), lang=hi. " if lang == "hi" else "")
                                         + "Reply with the JSON object only."}])


async def think(groq: Groq, messages: list[dict], name: str | None = None, location: str | None = None, lang: str = "en") -> dict:
    """LLM step: history in → {"reply", "end", "lang"} out (one retry if the reply comes back empty)."""
    t0 = time.perf_counter()
    out: dict = {}

    chat = build_chat(messages, name, location, lang)

    async def attempt() -> dict:
        # One pass over the models (quota-aware order). Retry only if a reply came back empty AND there is
        # still time — the old "always try twice" doubled the wait whenever every model was busy.
        for _ in range(2):
            try:
                r = await groq.chat_json(chat, max_tokens=REPLY_MAX_TOKENS, live=True)
            except Exception:  # noqa: BLE001
                r = {}
            if (r.get("reply") or "").strip():
                return r
            if time.perf_counter() - t0 > REPLY_BUDGET_S - 1.0:
                break
        return {}

    try:
        # Hard budget for a live call: if the AI can't answer in time, respond() falls back to the
        # script + facts instantly instead of leaving the caller in silence.
        out = await asyncio.wait_for(attempt(), timeout=REPLY_BUDGET_S)
    except asyncio.TimeoutError:
        out = {}
        groq.last_usage = {"model": "timeout", "budget_s": REPLY_BUDGET_S,
                           "attempts": (groq.last_usage or {}).get("attempts")}
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
    slot = faq.slot_confirmation(messages, lang)
    if slot:   # the lead chose the Property Expert time: confirm it back exactly and close politely
        print(f"[phone] slot confirmed", flush=True)
        return {"reply": slot, "end": True, "lang": lang, "_latency_s": round(time.perf_counter() - t0, 3),
                "_usage": {"model": "rule:slot-confirm", "prompt_tokens": 0, "completion_tokens": 0}}
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
            use_lang = "hi" if lang == "hi" else (out.get("lang") or lang)   # the lead's detected Hinglish wins
            out["lang"] = use_lang
            out["reply"] = faq.keep_language(faq.guard(out["reply"], messages, use_lang), use_lang)
        else:   # every model rate-limited/failed: answer from the script instead of "say that once more"
            fb = faq.fallback_reply(messages, lang)
            out.update({"reply": fb, "end": bool(re.search(r"have a lovely day|aapke time ke liye dhanyavaad", fb.lower())), "lang": lang,
                        "_usage": {"model": "rule:fallback", "prompt_tokens": 0, "completion_tokens": 0,
                                   "attempts": (out.get("_usage") or {}).get("attempts")}})   # keep why the AI failed
    reply = speakable(out.get("reply") or "")
    if out.get("end") and reply.rstrip().endswith("?"):
        out["end"] = False   # Divya is still asking something: never hang up on an open question
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
    transcript = "\n".join(("Lead: " if m["role"] == "user" else "Divya: ") + m["text"] for m in messages)
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
        **scoring.profile_fields(q, scoring.rules()),   # score 0-100 + reasons, objections, decider, next action
        "messages": messages, "raw": row.get("raw"),
    }
    update = {k: v for k, v in update.items() if v is not None}
    await sb.update("calls", {"vapi_call_id": f"eq.{_sid_key(call_sid)}"}, update)
    status = await apply_lead_update(sb, {**update, "lead_id": row.get("lead_id"), "vapi_call_id": _sid_key(call_sid)}, groq)
    from . import handoff
    await handoff.after_call(http, _sid_key(call_sid))   # CRM webhook (Settings → Sales team hand-off)
    if update.get("interest") == "hot":
        await telegram_alert(http, f"🔥 Hot lead (phone): {row.get('name') or 'Caller'}\n{update['summary']}")
    return {"finished": True, "interest": update.get("interest"), "lead_status": status}
