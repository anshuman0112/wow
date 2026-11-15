"""Divya on a phone call with Twilio ConversationRelay: replies are spoken WORD BY WORD.

    lead's phone ── Twilio: speech → text (streaming STT, fast end-of-speech) ──► WebSocket /ws/relay
                                                                                 │ 1. instant rules / FAQ (Redis) / reply cache (Redis)
                                                                                 │ 2. else Groq streams the reply word by word;
                                                                                 │    each finished sentence is checked by the
                                                                                 │    guardrails and sent at once
    lead's phone ◄── Twilio: text → voice, starts speaking at the FIRST sentence ◄┘
                     (the lead can interrupt: Twilio stops talking and tells us what was heard)

Same brain, same facts, same guardrails and the same after-call analysis as the <Gather> engine
(phone_agent.py); only the transport is live. Needs an always-on server (Vercel can't hold a
WebSocket): run `uvicorn backend.main:app` + a tunnel, or any free container host, and set
STREAM_BASE_URL + TWILIO_MODE=relay.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timezone
from xml.sax.saxutils import quoteattr

import httpx
from fastapi import WebSocket, WebSocketDisconnect

from . import cache, faq
from .clients import Groq, Supabase, shared_client
from .phone_agent import (HINTS, HISTORY_WINDOW, REPLY_MAX_TOKENS, _later, _sid_key, cached_reply, compact_prompt,
                          greeting, reply_key, rule_reply, speakable)
from .settings import settings

RELAY_RULES = """

PHONE (live voice): say ONLY the words Divya speaks — no JSON, no labels, no symbols, English letters only (Hinglish is fine). 1-2 short sentences. Put the short acknowledgement first ("Perfect." / "Got it.") so it can be spoken at once. If the call should end after this reply (time booked and confirmed, declined twice, don't call, wrong person, goodbye), end your reply with [END]. Garbled words -> ask them to repeat.
"""

_SYSTEM: tuple[int, str] | None = None


def system_relay() -> str:
    """Byte-identical on every turn (Groq caches this prefix), rebuilt only when Settings change."""
    global _SYSTEM
    from . import config_store
    if _SYSTEM is None or _SYSTEM[0] != config_store.version:
        _SYSTEM = (config_store.version, compact_prompt() + RELAY_RULES)
    return _SYSTEM[1]


def call_token(call_sid: str) -> str:
    """Proves the WebSocket was opened by the TwiML we served for this call (not by a stranger)."""
    return hmac.new(settings().twilio_token.encode(), f"relay:{call_sid}".encode(), hashlib.sha256).hexdigest()[:32]


def tts_voice(voice_id: str) -> tuple[str, str]:
    """Our voice ids (Twilio <Say> style, e.g. Google.en-IN-Chirp3-HD-Aoede) → ConversationRelay provider + voice."""
    provider, _, name = (voice_id or "").partition(".")
    if provider == "Polly":
        return "Amazon", name.replace("-Neural", "").replace("-Generative", "")
    return "Google", name or "en-IN-Chirp3-HD-Aoede"


def say_as(text: str) -> str:
    from .campaign import data
    for term, sound in data().get("phoneSayAs", []):   # pronunciation guide (Divyasree → Divya shree)
        text = re.sub(rf"\b{re.escape(term)}\b", sound, text)
    return text


def twiml_relay(ws_url: str, call_sid: str, lead_id: str, hello: str, voice: str, minimal: bool = False) -> str:
    if minimal:   # diagnostic: Twilio's defaults only (tells a settings problem apart from a blocked feature)
        return ('<?xml version="1.0" encoding="UTF-8"?><Response><Connect>'
                f'<ConversationRelay url={quoteattr(ws_url)} welcomeGreeting={quoteattr(say_as(hello))}>'
                f'<Parameter name="lead" value={quoteattr(lead_id)}/>'
                f'<Parameter name="token" value={quoteattr(call_token(call_sid))}/>'
                '</ConversationRelay></Connect><Say>The live connection could not start.</Say><Hangup/></Response>')
    provider, name = tts_voice(voice)
    return ('<?xml version="1.0" encoding="UTF-8"?><Response><Connect>'
            f'<ConversationRelay url={quoteattr(ws_url)} welcomeGreeting={quoteattr(say_as(hello))} '
            f'welcomeGreetingInterruptible="any" language="en-IN" ttsProvider="{provider}" voice={quoteattr(name)} '
            f'interruptible="any" hints={quoteattr(HINTS)}>'
            f'<Parameter name="lead" value={quoteattr(lead_id)}/>'
            f'<Parameter name="token" value={quoteattr(call_token(call_sid))}/>'
            '</ConversationRelay></Connect><Hangup/></Response>')


async def start(http: httpx.AsyncClient, call_sid: str, lead_id: str, ws_url: str, callback: bool = False,
                minimal: bool = False) -> str:
    """Twilio fetches this when the lead answers: create the session, return the ConversationRelay TwiML."""
    from . import voices
    sb = Supabase(http)
    lead = (await cache.get_lead(http, lead_id)) or {}
    if lead_id and not lead:
        rows = await sb.select("leads", {"select": "id,name,phone,location", "id": f"eq.{lead_id}"})
        lead = rows[0] if rows else {}
    hello = greeting(lead.get("name"), callback)
    voice = lead.get("voice") or await voices.selected(http)
    row = {"vapi_call_id": _sid_key(call_sid), "lead_id": lead.get("id"), "name": lead.get("name"),
           "phone": lead.get("phone"), "call_type": "twilioPhoneCall",
           "started_at": datetime.now(timezone.utc).isoformat(),
           "messages": [{"role": "assistant", "text": hello}],
           "raw": {"engine": "twilio-relay", "voice": voice, "callback": callback, "lang": "en",
                   "location": lead.get("location"), "session_store": "redis"}}
    if not await cache.set_session(http, call_sid, row):
        await sb.upsert("calls", row, "vapi_call_id")
    return twiml_relay(ws_url, call_sid, lead.get("id") or "", hello, voice, minimal)


# Sentence ends: . ! ? followed by a space — but not "Rs. 5", "e.g. x", "approx. 30", "No. 7", "Mr. X".
_ABBR = re.compile(r"(?:\b(?:rs|e\.g|i\.e|approx|no|mr|mrs|ms|dr|sq|ft|st|vs)\.)$", re.I)


def split_ready(buf: str) -> tuple[list[str], str]:
    """Cut finished sentences off the front of the buffer; the unfinished tail stays."""
    out, start = [], 0
    for m in re.finditer(r"[.!?](?=\s)", buf):
        piece = buf[start:m.end()]
        if _ABBR.search(piece.strip()):
            continue
        if piece.strip():
            out.append(piece.strip())
        start = m.end()
    return out, buf[start:]


class RelayCall:
    def __init__(self, ws: WebSocket, http: httpx.AsyncClient):
        self.ws, self.http = ws, http
        self.call_sid = ""
        self.row: dict = {}
        self.task: asyncio.Task | None = None
        self.closed = False
        self._end_flag = False

    @property
    def messages(self) -> list[dict]:
        return self.row.setdefault("messages", [])

    @property
    def raw(self) -> dict:
        return self.row.setdefault("raw", {})

    async def send(self, msg: dict) -> None:
        if not self.closed:
            await self.ws.send_text(json.dumps(msg))

    async def speak(self, text: str, last: bool = False) -> None:
        await self.send({"type": "text", "token": say_as(text) + ("" if last else " "), "last": last})

    async def save(self) -> None:
        await asyncio.gather(cache.set_session(self.http, self.call_sid, self.row), cache.set_quota(self.http))

    # ── one turn ──────────────────────────────────────────────────────────
    async def reply(self, speech: str) -> None:
        t_in = time.perf_counter()
        timing: dict = {}
        lang = faq.lang_of(speech, self.raw.get("lang", "en"))
        if lang != self.raw.get("lang", "en"):   # Hinglish: listen in Hindi too
            self.raw["lang"] = lang
            await self.send({"type": "language", "transcriptionLanguage": "hi-IN" if lang == "hi" else "en-IN"})
        self.messages.append({"role": "user", "text": speech})
        spoken: list[str] = []
        usage: dict = {}
        end = False

        async def say(text: str) -> None:
            if not spoken:
                timing["first_text_ms"] = round((time.perf_counter() - t_in) * 1000)
            spoken.append(text)
            await self.speak(text)

        groq = Groq(self.http)
        out = await rule_reply(self.http, self.messages, lang)
        key = None if out else reply_key(self.messages, lang)
        hit = await cached_reply(self.http, key)
        if out or hit:   # instant: rules, FAQ cache or reply cache (Redis)
            if hit:
                out = {"reply": hit, "end": False, "_usage": {"model": "reply-cache+redis"}}
            text = speakable(faq.keep_language(out["reply"] if out.get("_final") else faq.guard(out["reply"], self.messages, lang), lang))
            end = bool(out.get("end")) and not text.rstrip().endswith("?")
            if text and "?" not in text and not end:
                text = f"{text} {faq.next_question(self.messages + [{'role': 'assistant', 'text': text}], lang)}"
            usage = dict(out.get("_usage") or {})
            await say(text)
        else:   # the AI, word by word
            chat = self._chat(lang)
            buf = raw_all = ""
            stop = False
            async for piece in groq.stream_text(chat, max_tokens=REPLY_MAX_TOKENS):
                if "first_word_ms" not in timing:
                    timing["first_word_ms"] = round((time.perf_counter() - t_in) * 1000)
                buf += piece
                raw_all += piece
                ready, buf = split_ready(buf)
                for sentence in ready:
                    if await self._check_and_say(sentence, spoken, lang, say):
                        stop = True
                        break
                if stop:
                    break
            if not stop and buf.strip():
                await self._check_and_say(buf.strip(), spoken, lang, say)
            usage = dict(groq.last_usage or {})
            usage["llm_text"] = raw_all[:400]   # what the AI wrote, before guardrails (for review)
            full = " ".join(spoken)
            end = self._end_flag
            self._end_flag = False
            if not spoken:   # every model busy: the script answers instead of silence
                fb = faq.fallback_reply(self.messages, lang)
                usage["model"] = "rule:fallback"
                end = bool(re.search(r"have a lovely day|aapke time ke liye dhanyavaad", fb.lower()))
                await say(speakable(fb))
            elif "?" not in full and not end:   # never leave dead air: end the turn with the next question
                await say(faq.next_question(self.messages + [{"role": "assistant", "text": full}], lang))
            elif key and not end and not stop:   # cache only replies the guardrails left untouched
                first = (self.row.get("name") or "").split(" ")[0].lower()
                if not (first and first in full.lower()):
                    _later(cache.set_reply(self.http, key, full))
        await self.send({"type": "text", "token": "", "last": True})   # this turn's reply is complete
        text = " ".join(spoken)
        self.messages.append({"role": "assistant", "text": text})
        timing["reply_done_ms"] = round((time.perf_counter() - t_in) * 1000)
        usage["t_ms"] = timing | {"turn": len(self.messages) // 2}
        self.raw.setdefault("usage", []).append(usage)
        print(f"[latency] relay call={self.call_sid[-6:]} turn={usage['t_ms']['turn']} model={usage.get('model')} "
              f"first_text={timing.get('first_text_ms')}ms first_word={timing.get('first_word_ms')}ms "
              f"done={timing['reply_done_ms']}ms", flush=True)
        if end:
            self.raw["ended_reason"] = "assistant-ended-call"
            await self.save()
            # Let Twilio finish speaking the goodbye (~2.6 words/s), then end the session (TwiML hangs up).
            await asyncio.sleep(min(8.0, 0.6 + len(text.split()) / 2.6))
            await self.send({"type": "end"})
        else:
            await self.save()

    async def _check_and_say(self, sentence: str, spoken: list[str], lang: str, say) -> bool:
        """Guardrails on each finished sentence before it is spoken. True = stop the AI (we replaced its reply)."""
        if "[END]" in sentence:
            self._end_flag = True
        clean = speakable(sentence.replace("[END]", "")).strip()
        if not clean:
            return False
        so_far = " ".join(spoken)
        candidate = f"{so_far} {clean}".strip()
        fixed = faq.keep_language(faq.guard(candidate, self.messages, lang), lang)
        if fixed == candidate:
            await say(clean)
            return False
        # The guard changed the reply (invented a time, skipped a checkpoint, refused…): say its version.
        self.raw.setdefault("guarded", 0)
        self.raw["guarded"] += 1
        rest = fixed[len(so_far):].strip() if so_far and fixed.startswith(so_far) else fixed
        if rest:
            await say(rest)
        self._end_flag = False
        return True

    def _chat(self, lang: str) -> list[dict]:
        msgs = self.messages
        hist = msgs[-HISTORY_WINDOW:]
        if hist and hist[0]["role"] == "user" and msgs and msgs[0]["role"] == "assistant" and len(msgs) > len(hist):
            hist = [msgs[0]] + hist
        return ([{"role": "system", "content": system_relay()}] +
                [{"role": "user" if m["role"] == "user" else "assistant", "content": m["text"]} for m in hist] +
                [{"role": "system", "content": f"Lead name: {self.row.get('name') or 'unknown'}. "
                                               f"Lead location: {self.raw.get('location') or 'unknown'}. "
                  + ("The lead speaks Hindi/Hinglish: reply in simple Hinglish (English letters). " if lang == "hi" else "")
                  + "Say only Divya's words."}])

    def interrupted(self, heard: str) -> None:
        """The lead talked over Divya: stop the current reply and remember only what they actually heard."""
        if self.task and not self.task.done():
            self.task.cancel()
        if self.messages and self.messages[-1]["role"] == "assistant" and heard:
            self.messages[-1]["text"] = heard.strip()


async def handle(ws: WebSocket) -> None:
    await ws.accept()
    call = RelayCall(ws, shared_client())
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            kind = msg.get("type")
            if kind == "setup":
                params = msg.get("customParameters") or {}
                sid = msg.get("callSid", "")
                if not hmac.compare_digest(str(params.get("token", "")), call_token(sid)):
                    await ws.close(code=4403)
                    return
                call.call_sid = sid
                call.row = await cache.get_session(call.http, sid) or {
                    "vapi_call_id": _sid_key(sid), "lead_id": params.get("lead") or None, "messages": [],
                    "call_type": "twilioPhoneCall", "started_at": datetime.now(timezone.utc).isoformat(),
                    "raw": {"engine": "twilio-relay", "lang": "en"}}
            elif kind == "prompt" and msg.get("last", True):
                text = (msg.get("voicePrompt") or "").strip()
                if text and call.call_sid:
                    if call.task and not call.task.done():
                        call.task.cancel()
                    call.task = asyncio.create_task(call.reply(text))
            elif kind == "interrupt":
                call.interrupted(msg.get("utteranceUntilInterrupt") or "")
            elif kind == "error":
                print(f"[relay] twilio error: {str(msg)[:200]}", flush=True)
    except WebSocketDisconnect:
        pass
    finally:
        call.closed = True
        if call.task and not call.task.done():
            try:
                await asyncio.wait_for(asyncio.shield(call.task), timeout=3)
            except Exception:  # noqa: BLE001
                pass
        if call.call_sid:
            await call.save()   # the hang-up callback (/api/phone/status) analyses + saves the call
