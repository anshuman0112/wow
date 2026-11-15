"""Thin async clients for the external services (Supabase, Vapi, Twilio, Groq, Telegram)."""
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .settings import settings

TIMEOUT = httpx.Timeout(30.0, connect=25.0)   # generous connect: some networks resolve DNS slowly


class ServiceError(RuntimeError):
    def __init__(self, service: str, status: int, detail: str):
        super().__init__(f"{service} {status}: {detail[:300]}")
        self.service, self.status, self.detail = service, status, detail


def _raise(service: str, r: httpx.Response) -> None:
    if r.is_error:
        raise ServiceError(service, r.status_code, r.text)


# ── Supabase (PostgREST + Storage) ───────────────────────────────────────────
class Supabase:
    def __init__(self, http: httpx.AsyncClient):
        s = settings()
        self.http, self.base = http, s.supabase_url
        self.h = {"apikey": s.supabase_key, "Authorization": f"Bearer {s.supabase_key}"}

    async def select(self, table: str, params: dict[str, str]) -> list[dict]:
        r = await self.http.get(f"{self.base}/rest/v1/{table}", params=params, headers=self.h)
        _raise("supabase", r)
        return r.json()

    async def upsert(self, table: str, rows: Any, on_conflict: str, *, ignore_duplicates=False, returning=False) -> list[dict]:
        prefer = ("resolution=ignore-duplicates" if ignore_duplicates else "resolution=merge-duplicates") + \
                 (",return=representation" if returning else ",return=minimal")
        r = await self.http.post(f"{self.base}/rest/v1/{table}", params={"on_conflict": on_conflict},
                                 json=rows, headers={**self.h, "Prefer": prefer})
        _raise("supabase", r)
        return r.json() if returning and r.content else []

    async def update(self, table: str, filters: dict[str, str], patch: dict) -> None:
        r = await self.http.patch(f"{self.base}/rest/v1/{table}", params=filters, json=patch,
                                  headers={**self.h, "Prefer": "return=minimal"})
        _raise("supabase", r)

    async def upload(self, bucket: str, path: str, data: bytes, content_type: str) -> None:
        r = await self.http.post(f"{self.base}/storage/v1/object/{bucket}/{path}", content=data,
                                 headers={**self.h, "Content-Type": content_type, "x-upsert": "true"},
                                 timeout=httpx.Timeout(120.0, connect=25.0))
        _raise("supabase-storage", r)

    async def signed_url(self, bucket: str, path: str, expires_in: int) -> str:
        r = await self.http.post(f"{self.base}/storage/v1/object/sign/{bucket}/{path}",
                                 json={"expiresIn": expires_in}, headers=self.h)
        _raise("supabase-storage", r)
        return f"{self.base}/storage/v1{r.json()['signedURL']}"


# ── Vapi ─────────────────────────────────────────────────────────────────────
class Vapi:
    BASE = "https://api.vapi.ai"

    def __init__(self, http: httpx.AsyncClient):
        self.http = http
        self.h = {"Authorization": f"Bearer {settings().vapi_key}"}

    async def get_call(self, call_id: str) -> dict:
        r = await self.http.get(f"{self.BASE}/call/{call_id}", headers=self.h)
        _raise("vapi", r)
        return r.json()

    async def create_call(self, body: dict) -> dict:
        r = await self.http.post(f"{self.BASE}/call", json=body, headers=self.h)
        _raise("vapi", r)
        return r.json()


# ── Twilio ───────────────────────────────────────────────────────────────────
class Twilio:
    def __init__(self, http: httpx.AsyncClient):
        s = settings()
        self.http, self.sid = http, s.twilio_sid
        self.auth = (s.twilio_sid, s.twilio_token)

    async def call(self, to: str, from_: str, twiml_url: str, status_callback: str | None = None) -> dict:
        # Trial accounts may not send TwiML inline, so Twilio fetches it from our API (Url).
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Calls.json"
        data = {"To": to, "From": from_, "Url": twiml_url}
        if status_callback:
            data |= {"StatusCallback": status_callback, "StatusCallbackEvent": "completed"}
        r = await self.http.post(url, data=data, auth=self.auth)
        if r.status_code == 400 and status_callback and "parameter" in r.text.lower():
            # Trial accounts restrict some parameters — retry with the bare minimum.
            r = await self.http.post(url, data={"To": to, "From": from_, "Url": twiml_url}, auth=self.auth)
        _raise("twilio", r)
        return r.json()

    async def redirect(self, call_sid: str, twiml_url: str) -> bool:
        """Move a live call to new instructions right now (used to answer before Twilio's silence wait ends)."""
        r = await self.http.post(f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Calls/{call_sid}.json",
                                 data={"Url": twiml_url, "Method": "POST"}, auth=self.auth,
                                 timeout=httpx.Timeout(3.0, connect=1.5))
        if r.is_error:
            print(f"[twilio] redirect failed {r.status_code}: {r.text[:160]}", flush=True)
        return r.status_code < 300

    # Free-trial accounts can only call verified numbers. Verification: Twilio calls the number and the
    # person types the 6-digit code we show them on screen.
    async def is_verified(self, phone: str) -> bool:
        r = await self.http.get(f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/OutgoingCallerIds.json",
                                params={"PhoneNumber": phone}, auth=self.auth)
        _raise("twilio", r)
        if r.json().get("outgoing_caller_ids"):
            return True
        # The trial owner's own number is callable without being listed: a past completed call proves it.
        r = await self.http.get(f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Calls.json",
                                params={"To": phone, "Status": "completed", "PageSize": "1"}, auth=self.auth)
        _raise("twilio", r)
        return bool(r.json().get("calls"))

    async def start_verification(self, phone: str, name: str) -> str:
        r = await self.http.post(f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/OutgoingCallerIds.json",
                                 data={"PhoneNumber": phone, "FriendlyName": name[:60] or phone, "CallDelay": "2"},
                                 auth=self.auth)
        _raise("twilio", r)
        return str(r.json().get("validation_code", ""))


# ── Groq (OpenAI-compatible chat) ────────────────────────────────────────────
class Groq:
    def __init__(self, http: httpx.AsyncClient):
        s = settings()
        self.http, self.model = http, s.groq_model
        self.h = {"Authorization": f"Bearer {s.groq_key}"}

    async def json_chat(self, system: str, user: str) -> dict:
        body = {"model": self.model, "temperature": 0, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if self.model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = "low"
        r = await self.http.post("https://api.groq.com/openai/v1/chat/completions", json=body, headers=self.h,
                                 timeout=httpx.Timeout(60.0, connect=25.0))
        _raise("groq", r)
        return json.loads(r.json()["choices"][0]["message"]["content"])

    # Free-tier Groq allows 8k tokens/minute PER MODEL (a bucket that refills ~133 tokens/s).
    # Before: we tried models in a fixed order and only found out a model was full from a 429 —
    # each failed try cost time, and a few turns ran out the 3 s budget. Now every reply tells us
    # how many tokens that model has left, so we pick a model that can take the request up front.
    # Order = fastest first, measured on real calls: qwen3.8-27b has the shortest Groq queue (~0.05 s vs ~0.3 s)
    # and scored 98% on the conversation evaluation; gpt-oss-20b next; gpt-oss-120b as the backup.
    PHONE_MODELS = ("qwen/qwen3.8-27b", "openai/gpt-oss-20b", "openai/gpt-oss-120b")
    TPM = 8000

    def _room(self, model: str) -> float:
        """Tokens this model can take right now (estimated from its last reply + refill since)."""
        q = QUOTA.get(model)
        if not q:
            return self.TPM
        remaining, at = q
        return min(self.TPM, remaining + (time.time() - at) * self.TPM / 60)

    def _order(self, need: int) -> list[str]:
        fits = [m for m in self.PHONE_MODELS if self._room(m) >= need]
        rest = sorted((m for m in self.PHONE_MODELS if m not in fits), key=self._room, reverse=True)
        return fits + rest   # models that fit first (preferred order), then the fullest-bucket fallback

    async def chat_json(self, messages: list[dict], max_tokens: int = 400, *, live: bool = False) -> dict:
        """JSON chat. live=True (a phone turn): short timeouts, quota-aware model choice, timings recorded."""
        last = None
        need = sum(len(m.get("content") or "") for m in messages) // 4 + max_tokens
        attempts: list[dict] = []
        self.last_usage = {"model": "in-progress", "attempts": attempts}   # kept even if the caller times us out
        for model in self._order(need):
            body = {"model": model, "temperature": 0.3, "max_completion_tokens": max_tokens, "messages": messages}
            if not live:   # live turns skip Groq's strict JSON check: it rejected some replies with a 400 (~0.5 s lost)
                body["response_format"] = {"type": "json_object"}
            if model.startswith("openai/gpt-oss"):
                body["reasoning_effort"] = "low"
            t0 = time.perf_counter()
            try:
                r = await self.http.post("https://api.groq.com/openai/v1/chat/completions", json=body, headers=self.h,
                                         timeout=httpx.Timeout(1.8, connect=1.0) if live else httpx.Timeout(20.0, connect=5.0))
            except httpx.HTTPError as e:
                attempts.append({"model": model, "status": type(e).__name__, "ms": round((time.perf_counter() - t0) * 1000)})
                continue
            attempts.append({"model": model, "status": r.status_code, "ms": round((time.perf_counter() - t0) * 1000),
                             **({"why": r.text[:90]} if r.status_code != 200 else {})})
            _note_quota(model, r)
            if r.status_code in (429, 503) or (r.status_code == 400 and ("model" in r.text.lower() or "json_validate" in r.text)):
                last = r
                continue  # rate-limited, model unavailable or bad JSON → try the next free model
            _raise("groq", r)
            try:
                j = r.json()
                out = _loose_json(j["choices"][0]["message"]["content"] or "")
            except (json.JSONDecodeError, KeyError, IndexError):
                last = r
                continue
            u = j.get("usage") or {}
            # Usage is returned alongside the answer so callers can log/evaluate token cost.
            self.last_usage = {"model": model, "prompt_tokens": u.get("prompt_tokens"),
                               "cached_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens"),
                               "completion_tokens": u.get("completion_tokens"),
                               "seconds": round(float(u.get("total_time") or 0), 2),
                               "queue_s": round(float(u.get("queue_time") or 0), 2), "attempts": attempts}
            return out
        self.last_usage = {"model": "none", "attempts": attempts}
        _raise("groq", last) if last is not None else None
        return {}

    last_usage: dict | None = None

    async def stream_text(self, messages: list[dict], max_tokens: int = 250):
        """Word-by-word reply (Server-Sent Events). Yields text pieces as Groq writes them.
        Model choice is quota-aware like chat_json; we only switch model BEFORE the first word arrives."""
        need = sum(len(m.get("content") or "") for m in messages) // 4 + max_tokens
        attempts: list[dict] = []
        self.last_usage = {"model": "in-progress", "attempts": attempts}
        for model in self._order(need):
            body = {"model": model, "temperature": 0.3, "max_completion_tokens": max_tokens, "messages": messages,
                    "stream": True, "stream_options": {"include_usage": True}}
            if model.startswith("openai/gpt-oss"):
                body["reasoning_effort"] = "low"
            t0 = time.perf_counter()
            first = None
            try:
                async with self.http.stream("POST", "https://api.groq.com/openai/v1/chat/completions", json=body,
                                            headers=self.h, timeout=httpx.Timeout(4.0, connect=1.0)) as r:
                    _note_quota(model, r)
                    if r.status_code != 200:
                        await r.aread()
                        attempts.append({"model": model, "status": r.status_code, "ms": round((time.perf_counter() - t0) * 1000),
                                         "why": r.text[:90]})
                        continue
                    async for line in r.aiter_lines():
                        if not line.startswith("data: ") or line == "data: [DONE]":
                            continue
                        j = json.loads(line[6:])
                        u = (j.get("x_groq") or {}).get("usage") or j.get("usage")
                        if u:
                            self.last_usage.update({"prompt_tokens": u.get("prompt_tokens"),
                                                    "cached_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens"),
                                                    "completion_tokens": u.get("completion_tokens"),
                                                    "queue_s": round(float(u.get("queue_time") or 0), 2)})
                        piece = ((j.get("choices") or [{}])[0].get("delta") or {}).get("content")
                        if piece:
                            if first is None:
                                first = round((time.perf_counter() - t0) * 1000)
                            yield piece
                    attempts.append({"model": model, "status": 200, "first_word_ms": first,
                                     "ms": round((time.perf_counter() - t0) * 1000)})
                    self.last_usage["model"] = model
                    return
            except httpx.HTTPError as e:
                attempts.append({"model": model, "status": type(e).__name__, "ms": round((time.perf_counter() - t0) * 1000)})
                if first is not None:   # words were already spoken: don't start over with another model
                    self.last_usage["model"] = model
                    return
                continue
        self.last_usage["model"] = "none"


def _loose_json(text: str) -> dict:
    """The model's JSON reply, tolerating extra text around it; plain text becomes the reply itself."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    if text and "{" not in text:
        return {"reply": text}
    raise json.JSONDecodeError("no JSON object", text, 0)


# model -> (tokens remaining, unix time we learned it). Shared by all calls on this server instance and
# mirrored in Redis (see cache.get_quota / set_quota) so other instances start with the same picture.
QUOTA: dict[str, tuple[float, float]] = {}


def _note_quota(model: str, r: httpx.Response) -> None:
    left = r.headers.get("x-ratelimit-remaining-tokens")
    if r.status_code == 429:
        # Per-minute OR per-day limit: Groq says how long to wait. Park the model until then
        # (a "future" timestamp keeps its estimated room below zero until it is usable again).
        try:
            wait = float(r.headers.get("retry-after") or 0)
        except ValueError:
            wait = 0
        QUOTA[model] = (0.0, time.time() + max(wait, 5))
    elif left is not None:
        try:
            QUOTA[model] = (float(left), time.time())
        except ValueError:
            pass


# ── One shared connection pool per server instance ───────────────────────────
# Opening a new HTTPS connection (DNS + TLS handshake) to Groq/Redis on every phone turn costs time.
# Keep one client alive and reuse it; a new one is made only if the event loop changed.
_SHARED: tuple[object, httpx.AsyncClient] | None = None


def shared_client() -> httpx.AsyncClient:
    import asyncio
    global _SHARED
    loop = asyncio.get_running_loop()
    if _SHARED is None or _SHARED[0] is not loop or _SHARED[1].is_closed:
        _SHARED = (loop, httpx.AsyncClient(timeout=TIMEOUT, limits=httpx.Limits(max_keepalive_connections=20,
                                                                                keepalive_expiry=120)))
    return _SHARED[1]


# ── Telegram (optional hot-lead alerts) ──────────────────────────────────────
async def telegram_alert(http: httpx.AsyncClient, text: str) -> None:
    s = settings()
    if not (s.telegram_token and s.telegram_chat):
        return
    try:
        await http.post(f"https://api.telegram.org/bot{s.telegram_token}/sendMessage",
                        json={"chat_id": s.telegram_chat, "text": text})
    except httpx.HTTPError:
        pass  # alerts are best-effort
