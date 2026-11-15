"""Phone voice library: which voice Divya uses on real phone calls, chosen in the dashboard.

The voices are Twilio <Say> voices (Google Chirp3-HD, Amazon Polly). They only exist inside Twilio,
so the dashboard's ▶ Play button opens a tiny browser "call" (Twilio Voice SDK) to our
/api/twiml/voice-preview endpoint, which speaks a sample line in that exact voice.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

import httpx

from . import cache
from .campaign import data
from .clients import Supabase
from .settings import settings

REDIS_KEY = "phone_voice:v1"
SAMPLE = ("Hello, this is Divya from Divyasree Developers, calling about Whispers of the Wind, our villa plot "
          "community near Nandi Hills. Plots start at ninety-two point four lakh. Is this a good time for two minutes?")


def library() -> list[dict]:
    return data()["phoneVoices"]["library"]


def default_voice() -> str:
    return os.environ.get("PHONE_VOICE", "").strip() or data()["phoneVoices"]["default"]


def valid(voice_id: str) -> bool:
    return any(v["id"] == voice_id for v in library())


async def selected(http: httpx.AsyncClient) -> str:
    """The chosen voice: Redis (fast) → Supabase campaigns.phone_voice → campaign default."""
    if cache.fast_enough():
        try:
            v = await cache._cmd(http, "GET", REDIS_KEY)
            if v and valid(v):
                return v
        except Exception:  # noqa: BLE001
            pass
    try:
        rows = await Supabase(http).select("campaigns", {"select": "phone_voice", "id": f"eq.{settings().campaign_id}"})
        v = (rows[0].get("phone_voice") if rows else None) or ""
    except Exception:  # noqa: BLE001
        v = ""
    v = v if valid(v) else default_voice()
    if cache.fast_enough():
        try:
            await cache._cmd(http, "SET", REDIS_KEY, v)
        except Exception:  # noqa: BLE001
            pass
    return v


async def choose(http: httpx.AsyncClient, voice_id: str) -> str:
    await Supabase(http).update("campaigns", {"id": f"eq.{settings().campaign_id}"}, {"phone_voice": voice_id})
    if cache.enabled():
        try:
            await cache._cmd(http, "SET", REDIS_KEY, voice_id)
        except Exception:  # noqa: BLE001
            pass
    return voice_id


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def preview_token(ttl: int = 300) -> str | None:
    """Short-lived Twilio access token that can ONLY call our voice-preview TwiML app."""
    key, secret = os.environ.get("TWILIO_API_KEY", ""), os.environ.get("TWILIO_API_SECRET", "")
    app_sid, account = os.environ.get("TWILIO_TWIML_APP_SID", ""), settings().twilio_sid
    if not (key and secret and app_sid and account):
        return None
    now = int(time.time())
    header = {"typ": "JWT", "alg": "HS256", "cty": "twilio-fpa;v=1"}
    payload = {"jti": f"{key}-{now}", "iss": key, "sub": account, "iat": now, "nbf": now, "exp": now + ttl,
               "grants": {"identity": "voice-preview", "voice": {"outgoing": {"application_sid": app_sid}}}}
    signing = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}.{_b64(json.dumps(payload, separators=(',', ':')).encode())}"
    sig = hmac.new(secret.encode(), signing.encode(), hashlib.sha256).digest()
    return f"{signing}.{_b64(sig)}"
