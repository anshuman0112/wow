"""Redis session cache (Upstash, serverless REST) for live phone calls.

During a call the conversation lives in Redis (a few ms per turn) instead of a Supabase read +
write on every turn; the full call is written to Supabase once at the end (and on hang-up).

Why not cache replies too? Each reply is "answer + the next question in the script", and the next
question depends on what this call already covered — a cached reply could re-ask an answered
question. Token cost is cut instead by the compact prompt + provider prompt caching (static prefix).

Optional: without UPSTASH_REDIS_REST_URL / _TOKEN everything falls back to Supabase.
"""
from __future__ import annotations

import json
import os

import httpx

SESSION_TTL = 60 * 60          # 1 hour: longer than any call


def _conf() -> tuple[str, str]:
    return os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/"), os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")


def enabled() -> bool:
    url, token = _conf()
    return bool(url and token)


def fast_enough() -> bool:
    """Only put Redis on the live-call path when it is in a nearby region.
    Set REDIS_ON_HOT_PATH=1 once the database is in the same region as the API (e.g. Mumbai / ap-south-1);
    a far-away Redis (~500 ms) would add latency instead of removing it."""
    return enabled() and os.environ.get("REDIS_ON_HOT_PATH", "0") == "1"


async def _cmd(http: httpx.AsyncClient, *args) -> object:
    url, token = _conf()
    r = await http.post(url, json=list(args), headers={"Authorization": f"Bearer {token}"},
                        timeout=httpx.Timeout(5.0, connect=5.0))
    r.raise_for_status()
    return r.json().get("result")


async def get_session(http: httpx.AsyncClient, call_sid: str) -> dict | None:
    if not fast_enough():
        return None
    try:
        raw = await _cmd(http, "GET", f"call:{call_sid}")
        return json.loads(raw) if raw else None
    except (httpx.HTTPError, json.JSONDecodeError):
        return None


async def put_lead(http: httpx.AsyncClient, lead: dict) -> None:
    """Stash the lead when 'Call now' is pressed so the call can start without a database round-trip."""
    if fast_enough() and lead.get("id"):
        try:
            await _cmd(http, "SET", f"lead:{lead['id']}", json.dumps(lead), "EX", 900)
        except httpx.HTTPError:
            pass


async def get_lead(http: httpx.AsyncClient, lead_id: str) -> dict | None:
    if not (fast_enough() and lead_id):
        return None
    try:
        raw = await _cmd(http, "GET", f"lead:{lead_id}")
        return json.loads(raw) if raw else None
    except (httpx.HTTPError, json.JSONDecodeError):
        return None


FAQ_TTL = 60 * 60 * 24 * 30     # answers come from campaign facts; bump FAQ_VERSION when facts change
FAQ_VERSION = "v4"


async def get_faq(http: httpx.AsyncClient, intent: str, lang: str) -> str | None:
    if not fast_enough():
        return None
    try:
        return await _cmd(http, "GET", f"faq:{FAQ_VERSION}:{intent}:{lang}")
    except httpx.HTTPError:
        return None


async def set_faq(http: httpx.AsyncClient, intent: str, lang: str, answer: str) -> None:
    if fast_enough():
        try:
            await _cmd(http, "SET", f"faq:{FAQ_VERSION}:{intent}:{lang}", answer, "EX", FAQ_TTL)
        except httpx.HTTPError:
            pass


async def count_faq(http: httpx.AsyncClient, intents: list[str]) -> None:
    """Most-asked analytics: one counter per question type."""
    if fast_enough():
        for i in intents:
            try:
                await _cmd(http, "INCR", f"faq:hits:{i}")
            except httpx.HTTPError:
                pass


async def faq_stats(http: httpx.AsyncClient, intents: list[str]) -> dict[str, int]:
    if not enabled():
        return {}
    try:
        vals = await _cmd(http, "MGET", *[f"faq:hits:{i}" for i in intents]) or []
        return {i: int(v or 0) for i, v in zip(intents, vals)}
    except httpx.HTTPError:
        return {}


async def set_session(http: httpx.AsyncClient, call_sid: str, session: dict) -> bool:
    if not fast_enough():
        return False
    try:
        await _cmd(http, "SET", f"call:{call_sid}", json.dumps(session), "EX", SESSION_TTL)
        return True
    except httpx.HTTPError:
        return False


async def get_quota(http: httpx.AsyncClient) -> None:
    """Load Groq's per-model token budget into this server instance (newer readings win)."""
    from .clients import QUOTA
    if not fast_enough():
        return
    try:
        raw = await _cmd(http, "GET", "groq:quota")
        for model, (left, at) in (json.loads(raw) if raw else {}).items():
            if model not in QUOTA or QUOTA[model][1] < at:
                QUOTA[model] = (float(left), float(at))
    except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError):
        pass


async def set_quota(http: httpx.AsyncClient) -> None:
    from .clients import QUOTA
    if fast_enough() and QUOTA:
        try:
            await _cmd(http, "SET", "groq:quota", json.dumps(QUOTA), "EX", 120)
        except httpx.HTTPError:
            pass


REPLY_TTL = 60 * 60 * 24 * 7   # a week; the key includes the Settings version, so edits start fresh


async def get_reply(http: httpx.AsyncClient, key: str) -> str | None:
    if not fast_enough():
        return None
    try:
        return await _cmd(http, "GET", key)
    except httpx.HTTPError:
        return None


async def set_reply(http: httpx.AsyncClient, key: str, reply: str) -> None:
    if fast_enough() and reply:
        try:
            await _cmd(http, "SET", key, reply, "EX", REPLY_TTL)
        except httpx.HTTPError:
            pass


async def claim(http: httpx.AsyncClient, key: str, ttl: int = 300) -> bool:
    """First caller wins (Redis SET NX): a turn is answered once, by the instant path OR the normal one."""
    if not fast_enough():
        return True
    try:
        return await _cmd(http, "SET", key, "1", "NX", "EX", ttl) == "OK"
    except httpx.HTTPError:
        return True


async def put_text(http: httpx.AsyncClient, key: str, value: str, ttl: int = 300) -> None:
    if fast_enough():
        try:
            await _cmd(http, "SET", key, value, "EX", ttl)
        except httpx.HTTPError:
            pass


async def get_text(http: httpx.AsyncClient, key: str) -> str | None:
    if not fast_enough():
        return None
    try:
        return await _cmd(http, "GET", key)
    except httpx.HTTPError:
        return None
