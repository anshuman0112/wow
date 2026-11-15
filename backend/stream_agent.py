"""Aanya on a real phone call with LIVE audio streaming (low latency).

Why: the <Gather> engine waits for Twilio to decide you finished talking, then makes a web request,
then Twilio synthesises the whole reply before playing it. Here everything is streamed:

    lead's phone ══ Twilio Media Stream (20 ms μ-law frames over a WebSocket) ══► this server
        1. VAD (voice activity detection) on every frame → we know the moment the lead stops (~0.6 s)
        2. Groq Whisper turbo → text            (~0.2–0.4 s)
        3. reply: FAQ cache (0 tokens, instant) or Groq LLM streamed sentence by sentence
        4. ElevenLabs flash streams μ-law audio for sentence 1 while sentence 2 is still being written
    lead's phone ◄══ audio frames played as they arrive; lead can interrupt (barge-in) at any time

Spoken sentences are cached (memory + Redis), so FAQ answers and script questions cost no
TTS characters the second time: "voice caching".
"""
from __future__ import annotations

import array
import asyncio
import base64
import hashlib
import hmac
import io
import json
import math
import re
import time
import wave
from collections import OrderedDict
from datetime import datetime, timezone

import httpx
from fastapi import WebSocket, WebSocketDisconnect

from . import cache, faq
from .clients import Groq, Supabase
from .phone_agent import HINTS, MAX_TURNS, _sid_key, build_chat, compact_prompt, greeting
from .settings import settings

# ── audio helpers (Twilio sends 8 kHz μ-law; Python 3.13+ has no audioop) ─────
def _ulaw_to_linear(b: int) -> int:
    b = ~b & 0xFF
    sign, exp, mant = b & 0x80, (b >> 4) & 0x07, b & 0x0F
    s = (((mant << 3) + 0x84) << exp) - 0x84
    return -s if sign else s


ULAW = [_ulaw_to_linear(i) for i in range(256)]
ULAW_SQ = [v * v for v in ULAW]
FRAME_MS = 20


def frame_rms(frame: bytes) -> float:
    return math.sqrt(sum(ULAW_SQ[b] for b in frame) / max(len(frame), 1))


def ulaw_to_wav(ulaw: bytes) -> bytes:
    pcm = array.array("h", (ULAW[b] for b in ulaw)).tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(pcm)
    return buf.getvalue()


def call_token(call_sid: str) -> str:
    """Proves a WebSocket was opened by the TwiML we served for this call (not by a stranger)."""
    return hmac.new(settings().twilio_token.encode(), call_sid.encode(), hashlib.sha256).hexdigest()[:32]


def twiml_stream(ws_url: str, call_sid: str, lead_id: str) -> str:
    from xml.sax.saxutils import quoteattr
    return ('<?xml version="1.0" encoding="UTF-8"?><Response><Connect>'
            f'<Stream url={quoteattr(ws_url)}>'
            f'<Parameter name="lead" value={quoteattr(lead_id)}/>'
            f'<Parameter name="token" value={quoteattr(call_token(call_sid))}/>'
            '</Stream></Connect><Hangup/></Response>')


# ── speech to text: Groq Whisper (free) ─────────────────────────────────────
WHISPER_JUNK = re.compile(r"^\W*(thank you|thanks for watching|you|bye|subtitles.*|\.+)\W*$", re.I)


async def transcribe(http: httpx.AsyncClient, ulaw: bytes) -> str:
    s = settings()
    try:
        r = await http.post("https://api.groq.com/openai/v1/audio/transcriptions",
                            headers={"Authorization": f"Bearer {s.groq_key}"},
                            files={"file": ("turn.wav", ulaw_to_wav(ulaw), "audio/wav")},
                            data={"model": "whisper-large-v3-turbo", "response_format": "verbose_json",
                                  "temperature": "0", "prompt": "Hinglish phone call in English letters. " + HINTS},
                            timeout=httpx.Timeout(4.0, connect=2.0))
    except httpx.HTTPError as e:
        print(f"[stream] stt error {type(e).__name__}", flush=True)
        return ""
    if r.is_error:
        print(f"[stream] stt {r.status_code} {r.text[:200]}", flush=True)
        return ""
    j = r.json()
    segs = [sg for sg in j.get("segments") or [] if (sg.get("no_speech_prob") or 0) < 0.6]
    text = " ".join(sg.get("text", "").strip() for sg in segs).strip() if j.get("segments") else (j.get("text") or "").strip()
    if WHISPER_JUNK.match(text) and len(ulaw) < 8000 * 1.2:   # Whisper "hears" these in short noise
        return ""
    return text


# ── text to speech: ElevenLabs flash, streamed, with a voice cache ──────────
_TTS_MEM: OrderedDict[str, bytes] = OrderedDict()


def _tts_key(text: str) -> str:
    return "tts:v1:" + hashlib.sha1(f"{settings().stream_voice_id}|{text}".encode()).hexdigest()


async def tts_stream(http: httpx.AsyncClient, text: str, out: asyncio.Queue) -> None:
    """Push μ-law audio chunks for `text` into `out` (None = finished). Cache hits are instant."""
    key = _tts_key(text)
    hit = _TTS_MEM.get(key)
    if hit is None and cache.fast_enough():
        try:
            raw = await asyncio.wait_for(cache._cmd(http, "GET", key), timeout=0.3)
            hit = base64.b64decode(raw) if raw else None
        except Exception:  # noqa: BLE001
            hit = None
    if hit:
        _TTS_MEM[key] = hit
        _TTS_MEM.move_to_end(key)
        await out.put(hit)
        await out.put(None)
        return
    s = settings()
    audio = bytearray()
    try:
        async with http.stream("POST", f"https://api.elevenlabs.io/v1/text-to-speech/{s.stream_voice_id}/stream",
                               params={"output_format": "ulaw_8000", "optimize_streaming_latency": "3"},
                               headers={"xi-api-key": s.elevenlabs_key},
                               json={"text": text, "model_id": "eleven_flash_v2_5",
                                     "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "speed": 1.0}},
                               timeout=httpx.Timeout(10.0, connect=3.0)) as r:
            if r.is_error:
                print(f"[stream] tts {r.status_code} {(await r.aread())[:200]!r}", flush=True)
            else:
                async for chunk in r.aiter_bytes():
                    if chunk:
                        audio += chunk
                        await out.put(bytes(chunk))
    except httpx.HTTPError as e:
        print(f"[stream] tts error {type(e).__name__}", flush=True)
    await out.put(None)
    if audio:
        _TTS_MEM[key] = bytes(audio)
        while len(_TTS_MEM) > 300:
            _TTS_MEM.popitem(last=False)
        if cache.fast_enough():
            asyncio.create_task(_store_tts(http, key, bytes(audio)))


async def _store_tts(http: httpx.AsyncClient, key: str, audio: bytes) -> None:
    try:
        await cache._cmd(http, "SET", key, base64.b64encode(audio).decode(), "EX", 60 * 60 * 24 * 30)
    except Exception:  # noqa: BLE001
        pass


# ── reply generation: FAQ cache, rules, or Groq streamed sentence by sentence ─
STREAM_RULES = """

# PHONE MODE (live voice call)
Reply with ONLY the words you will say out loud: 1–2 short sentences, English letters only (Hinglish is fine),
no symbols, lists, markdown or JSON. If the call should finish now (callback booked and confirmed, lead declined
twice, asked not to be called, wrong person, or said goodbye), say your goodbye line and then write <END>.
If the lead's words look garbled or empty, politely ask them to repeat."""
SYSTEM_STREAM = compact_prompt() + STREAM_RULES
SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")
PLAIN = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "‑": "-", "–": "-",
                       "—": ", ", "*": "", "#": ""})


def stream_chat(messages: list[dict], name: str | None, location: str | None, lang: str) -> list[dict]:
    chat = build_chat(messages, name, location, lang)
    chat[0] = {"role": "system", "content": SYSTEM_STREAM}
    chat[-1]["content"] = chat[-1]["content"].replace("Reply with the JSON object only.", "Reply with the spoken words only.")
    return chat


async def llm_sentences(http: httpx.AsyncClient, chat: list[dict]):
    """Yield sentences as the model writes them (first sentence arrives long before the reply is done)."""
    s = settings()
    for model in Groq.PHONE_MODELS:
        body = {"model": model, "temperature": 0.3, "max_completion_tokens": 300, "stream": True, "messages": chat}
        if model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = "low"
        buf, got_any = "", False
        try:
            async with http.stream("POST", "https://api.groq.com/openai/v1/chat/completions", json=body,
                                   headers={"Authorization": f"Bearer {s.groq_key}"},
                                   timeout=httpx.Timeout(3.0, connect=2.0)) as r:
                if r.status_code in (429, 503, 400):
                    print(f"[stream] llm {model} {r.status_code} → next model", flush=True)
                    continue
                if r.is_error:
                    continue
                async for line in r.aiter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    try:
                        delta = json.loads(line[6:])["choices"][0]["delta"].get("content") or ""
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    buf += delta.translate(PLAIN)
                    parts = SENTENCE_END.split(buf)
                    for p in parts[:-1]:
                        if p.strip():
                            got_any = True
                            yield p.strip()
                    buf = parts[-1]
        except httpx.HTTPError as e:
            print(f"[stream] llm {model} {type(e).__name__}", flush=True)
            if got_any:
                return
            continue
        if buf.strip():
            got_any = True
            yield buf.strip()
        if got_any:
            return


# ── one live call ────────────────────────────────────────────────────────────
LIVE: dict[str, "LiveCall"] = {}


class LiveCall:
    def __init__(self, ws: WebSocket, http: httpx.AsyncClient):
        self.ws, self.http = ws, http
        self.stream_sid = self.call_sid = ""
        self.row: dict = {}
        self.lang = "en"
        # VAD state
        self.noise = 200.0
        self.in_speech = False
        self.voiced_run = self.silent_run = 0
        self.utter = bytearray()
        self.preroll: list[bytes] = []
        self.last_activity = time.monotonic()
        # playback state
        self.pending_marks: dict[str, str] = {}   # mark name → sentence text
        self.mark_n = 0
        self.played: set[str] = set()             # marks Twilio confirmed as heard
        self.playback_idle = asyncio.Event()
        self.playback_idle.set()
        self.reply_task: asyncio.Task | None = None
        self.reply_spoke = False
        self.turns: asyncio.Queue = asyncio.Queue()
        self.ending = False
        self.closed = asyncio.Event()
        self.silences = 0
        self.t_user_end = 0.0

    # ---------- helpers ----------
    @property
    def messages(self) -> list[dict]:
        return self.row.setdefault("messages", [])

    async def send(self, msg: dict) -> None:
        try:
            await self.ws.send_text(json.dumps(msg))
        except Exception:  # noqa: BLE001
            pass

    async def save(self) -> None:
        if not await cache.set_session(self.http, self.call_sid, self.row):
            try:
                await Supabase(self.http).upsert("calls", self.row, "vapi_call_id")
            except Exception as e:  # noqa: BLE001
                print(f"[stream] save failed {e}", flush=True)

    # ---------- start ----------
    async def on_start(self, start: dict) -> bool:
        s = settings()
        self.stream_sid, self.call_sid = start.get("streamSid", ""), start.get("callSid", "")
        p = start.get("customParameters") or {}
        if start.get("accountSid") != s.twilio_sid or not hmac.compare_digest(p.get("token", ""), call_token(self.call_sid)):
            print("[stream] rejected stream: bad account or token", flush=True)
            return False
        LIVE[self.call_sid] = self
        lead_id = p.get("lead") or ""
        lead = (await cache.get_lead(self.http, lead_id)) or {}
        if lead_id and not lead:
            try:
                rows = await Supabase(self.http).select("leads", {"select": "id,name,phone,location", "id": f"eq.{lead_id}"})
                lead = rows[0] if rows else {}
            except Exception:  # noqa: BLE001
                lead = {}
        hello = greeting(lead.get("name"))
        self.row = {
            "vapi_call_id": _sid_key(self.call_sid), "lead_id": lead.get("id"), "name": lead.get("name"),
            "phone": lead.get("phone"), "call_type": "twilioPhoneCall",
            "started_at": datetime.now(timezone.utc).isoformat(), "messages": [],
            "raw": {"engine": "twilio-stream", "lang": "en", "location": lead.get("location"), "latency_ms": [],
                    "session_store": "redis" if cache.fast_enough() else "supabase"},
        }
        asyncio.create_task(self.worker())
        asyncio.create_task(self.idle_watch())
        self.reply_task = asyncio.create_task(self.speak_reply(iter_text([hello]), end=False))
        return True

    # ---------- audio in: VAD ----------
    def on_media(self, payload: str) -> None:
        frame = base64.b64decode(payload)
        rms = frame_rms(frame)
        speaking = not self.playback_idle.is_set()
        # louder threshold while Aanya talks, so line echo of her own voice doesn't count as the lead
        threshold = max(self.noise * (4.0 if speaking else 2.8), 900 if speaking else 450)
        voiced = rms > threshold
        if not voiced and not self.in_speech:
            self.noise = 0.95 * self.noise + 0.05 * min(rms, 2000)   # track the line's background noise
        if not self.in_speech:
            self.preroll = (self.preroll + [frame])[-15:]           # keep 300 ms before the onset
            self.voiced_run = self.voiced_run + 1 if voiced else 0
            needed = 12 if speaking else 3                          # 240 ms to barge in, 60 ms otherwise
            if self.voiced_run >= needed:
                self.in_speech, self.silent_run = True, 0
                self.utter = bytearray(b"".join(self.preroll))
                self.last_activity = time.monotonic()
                if speaking:
                    asyncio.create_task(self.barge_in())
            return
        self.utter += frame
        self.silent_run = 0 if voiced else self.silent_run + 1
        too_long = len(self.utter) > 8000 * 15
        if self.silent_run * FRAME_MS >= settings().stream_end_silence_ms or too_long:
            self.in_speech, self.voiced_run = False, 0
            self.t_user_end = time.perf_counter()
            self.last_activity = time.monotonic()
            voiced_ms = len(self.utter) / 8 - self.silent_run * FRAME_MS
            if voiced_ms >= 250:
                self.turns.put_nowait(bytes(self.utter))
            self.utter = bytearray()

    async def barge_in(self) -> None:
        """Lead started talking over Aanya: stop her immediately."""
        await self.send({"event": "clear", "streamSid": self.stream_sid})
        self.pending_marks.clear()   # Twilio echoes cleared marks back; they were never heard
        self.playback_idle.set()
        if self.reply_task and not self.reply_task.done() and not self.ending:
            self.reply_task.cancel()
        print("[stream] barge-in", flush=True)

    # ---------- turns ----------
    async def worker(self) -> None:
        while not self.closed.is_set():
            ulaw = await self.turns.get()
            t0 = time.perf_counter()
            text = await transcribe(self.http, ulaw)
            stt_ms = round((time.perf_counter() - t0) * 1000)
            print(f"[stream] heard ({stt_ms} ms): {text!r}", flush=True)
            if not text or self.ending:
                continue
            self.silences = 0
            if self.reply_task and not self.reply_task.done():
                self.reply_task.cancel()   # lead kept talking: answer everything together
                if not self.reply_spoke and self.messages and self.messages[-1]["role"] == "user":
                    text = self.messages.pop()["text"] + " " + text
            self.messages.append({"role": "user", "text": text})
            self.reply_task = asyncio.create_task(self.reply(stt_ms))

    async def reply(self, stt_ms: int) -> None:
        msgs, row = self.messages, self.row
        speech = msgs[-1]["text"]
        self.lang = faq.lang_of(speech, self.lang)
        lang = self.lang
        end_after = len(msgs) >= MAX_TURNS * 2
        intents = faq.detect(speech)
        if intents:
            await cache.count_faq(self.http, intents)
            text = f"{faq.answer(intents, lang)} {faq.next_question(msgs, lang)}"
            source = iter_text(SENTENCE_END.split(text))
            model = "faq-cache"
        elif (objection := faq.budget_objection(msgs, lang) or faq.location_objection(msgs, lang)):
            source, model = iter_text(SENTENCE_END.split(objection)), "rule:objection"
        else:
            source, model = self.guarded_llm(msgs, lang), "groq-stream"
        row["raw"]["lang"] = lang
        row["raw"].setdefault("usage", []).append({"model": model, "stt_ms": stt_ms})
        await self.speak_reply(source, end=end_after)

    async def guarded_llm(self, msgs: list[dict], lang: str):
        """LLM sentences with the same guardrails as the Gather engine, applied sentence by sentence."""
        chat = stream_chat(msgs, self.row.get("name"), self.row["raw"].get("location"), lang)
        said: list[str] = []
        got = False
        try:
            async with asyncio.timeout(4.0):
                async for sent in llm_sentences(self.http, chat):
                    got = True
                    end = "<END>" in sent
                    clean = sent.replace("<END>", "").strip()
                    if clean:
                        fixed = faq.guard(clean, msgs + [{"role": "assistant", "text": " ".join(said)}], lang)
                        if fixed != clean:          # invented a slot / skipped the pitch → use the safe line, stop
                            yield fixed
                            return
                        said.append(clean)
                        yield clean
                    if end:
                        yield "<END>"
                        return
        except TimeoutError:
            print("[stream] llm budget exceeded", flush=True)
        if not got:
            yield faq.fallback_reply(msgs, lang)

    async def speak_reply(self, sentences, end: bool) -> None:
        """Speak sentences as they arrive; TTS of sentence n+1 starts while sentence n plays."""
        self.reply_spoke = False
        said: list[tuple[str, str]] = []
        queues: asyncio.Queue = asyncio.Queue()
        ended = end

        async def producer():
            nonlocal ended
            async for sent in sentences:
                if sent == "<END>":
                    ended = True
                    continue
                q: asyncio.Queue = asyncio.Queue()
                asyncio.create_task(tts_stream(self.http, sent, q))
                await queues.put((sent, q))
            await queues.put(None)

        prod = asyncio.create_task(producer())
        first = True
        try:
            while (item := await queues.get()) is not None:
                sent, q = item
                while (chunk := await q.get()) is not None:
                    if first and self.t_user_end:
                        ms = round((time.perf_counter() - self.t_user_end) * 1000)
                        self.row["raw"]["latency_ms"].append(ms)
                        print(f"[stream] first audio {ms} ms after the lead stopped talking", flush=True)
                    first = False
                    self.reply_spoke = True
                    self.playback_idle.clear()
                    await self.send({"event": "media", "streamSid": self.stream_sid,
                                     "media": {"payload": base64.b64encode(chunk).decode()}})
                self.mark_n += 1
                name = f"s{self.mark_n}"
                self.pending_marks[name] = sent
                said.append((name, sent))
                await self.send({"event": "mark", "streamSid": self.stream_sid, "mark": {"name": name}})
        except asyncio.CancelledError:
            prod.cancel()
            self._record(said, interrupted=True)
            raise
        self._record(said)
        if ended:
            self.ending = True
            await self.playback_idle.wait()
            await asyncio.sleep(0.4)
            self.row["raw"]["ended_reason"] = "assistant-ended-call"
            await self.save()
            await self.ws.close()

    def _record(self, said: list[tuple[str, str]], interrupted: bool = False) -> None:
        # interrupted → keep only what the lead actually heard (Twilio returned its mark before the barge-in)
        heard = [t for n, t in said if n in self.played] if interrupted else [t for _, t in said]
        if heard:
            self.messages.append({"role": "assistant", "text": " ".join(heard)})
            asyncio.create_task(self.save())

    def on_mark(self, name: str) -> None:
        if self.pending_marks.pop(name, None) is not None:
            self.played.add(name)
        if not self.pending_marks:
            self.playback_idle.set()
            self.last_activity = time.monotonic()

    async def idle_watch(self) -> None:
        """Lead silent for 8 s after Aanya finished → nudge once, then say goodbye."""
        while not self.closed.is_set():
            await asyncio.sleep(1)
            busy = self.in_speech or not self.playback_idle.is_set() or (self.reply_task and not self.reply_task.done())
            if busy or self.ending:
                continue
            if time.monotonic() - self.last_activity > 8:
                self.silences += 1
                self.last_activity = time.monotonic()
                if self.silences >= 2:
                    self.row["raw"]["ended_reason"] = "silence-timed-out"
                    line = "I'll try you another time. Thank you, and have a lovely day!"
                    self.reply_task = asyncio.create_task(self.speak_reply(iter_text([line]), end=True))
                else:
                    line = "Are you still there?" if self.lang == "en" else "Kya aap sun pa rahe hain?"
                    self.reply_task = asyncio.create_task(self.speak_reply(iter_text([line]), end=False))

    async def on_stop(self) -> None:
        if self.reply_task and not self.reply_task.done():
            self.reply_task.cancel()
        self.row.setdefault("raw", {}).setdefault("ended_reason", "customer-ended-call")
        if self.row.get("vapi_call_id"):
            lat = self.row["raw"].get("latency_ms") or []
            if lat:
                self.row["raw"]["latency_avg_ms"] = round(sum(lat) / len(lat))
            await self.save()
        self.closed.set()


async def iter_text(items):
    for t in items:
        if t and t.strip():
            yield t.strip()


async def handle(ws: WebSocket) -> None:
    await ws.accept()
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0),
                                 limits=httpx.Limits(max_keepalive_connections=10)) as http:
        call = LiveCall(ws, http)
        try:
            while True:
                msg = json.loads(await ws.receive_text())
                ev = msg.get("event")
                if ev == "media":
                    if call.stream_sid:
                        call.on_media(msg["media"]["payload"])
                elif ev == "start":
                    if not await call.on_start(msg.get("start") or {}):
                        await ws.close(code=1008)
                        return
                elif ev == "mark":
                    call.on_mark((msg.get("mark") or {}).get("name", ""))
                elif ev == "stop":
                    break
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await call.on_stop()
            LIVE.pop(call.call_sid, None)
            await asyncio.sleep(0)   # let the final save task run before the client closes
