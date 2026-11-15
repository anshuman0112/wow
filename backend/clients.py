"""Thin async clients for the external services (Supabase, Vapi, Twilio, Groq, Telegram)."""
from __future__ import annotations

import json
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

    # Free-tier Groq allows ~8k tokens/minute PER MODEL, so live phone turns rotate across models on 429.
    PHONE_MODELS = ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b")

    async def chat_json(self, messages: list[dict], max_tokens: int = 400) -> dict:
        last = None
        for model in self.PHONE_MODELS:
            body = {"model": model, "temperature": 0.3, "max_completion_tokens": max_tokens,
                    "response_format": {"type": "json_object"}, "messages": messages}
            if model.startswith("openai/gpt-oss"):
                body["reasoning_effort"] = "low"
            try:
                r = await self.http.post("https://api.groq.com/openai/v1/chat/completions", json=body, headers=self.h,
                                         timeout=httpx.Timeout(2.5, connect=2.0))   # live call: a slow model is skipped fast
            except httpx.HTTPError:
                continue
            if r.status_code in (429, 503) or (r.status_code == 400 and ("model" in r.text.lower() or "json_validate" in r.text)):
                last = r
                continue  # rate-limited, model unavailable or bad JSON → try the next free model
            _raise("groq", r)
            try:
                j = r.json()
                out = json.loads(j["choices"][0]["message"]["content"] or "{}")
            except (json.JSONDecodeError, KeyError, IndexError):
                last = r
                continue
            u = j.get("usage") or {}
            # Usage is returned alongside the answer so callers can log/evaluate token cost.
            self.last_usage = {"model": model, "prompt_tokens": u.get("prompt_tokens"),
                               "cached_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens"),
                               "completion_tokens": u.get("completion_tokens"),
                               "seconds": round(float(u.get("total_time") or 0), 2)}
            return out
        _raise("groq", last) if last is not None else None
        return {}

    last_usage: dict | None = None


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
