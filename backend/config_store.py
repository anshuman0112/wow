"""Settings page: everything a sales manager can change without code, applied to every call.

    questions      what Divya asks at each step (English + Hindi)
    scoring        points per answer, tone adjustments, Hot/Warm pass marks, must-haves for Hot
    calling_hours  when automatic calls may go out (IST)
    retry          re-attempt cadence when nobody picks up, e.g. ["10m", "2h", "next 11:00"]
    speed_to_lead  call new leads automatically within seconds of arriving
    handoff        sales team WhatsApp number + CRM webhook URL

Stored in campaigns.settings (Supabase), cached in Redis + memory for 30 s, so a change reaches every
call within about half a minute. Saving also re-syncs the browser (Vapi) assistant's prompt.
"""
from __future__ import annotations

import json
import re
import time

import httpx

from . import cache
from .campaign import data
from .clients import Supabase
from .settings import settings

REDIS_KEY = "settings:v1"
TTL_S = 30
QUESTION_KEYS = ("intent", "geography", "budget", "timeline", "decision", "pitch", "callback")

_cfg: dict | None = None
_loaded_at = 0.0
version = 0   # bumps whenever the settings change, so prompts are rebuilt


def defaults() -> dict:
    d = data()
    return {
        "questions": {k: dict(d["nextQuestion"][k]) for k in QUESTION_KEYS if k in d["nextQuestion"]},
        "scoring": json.loads(json.dumps(d.get("scoring") or {})),
        "calling_hours": {"start": 9, "end": 21},
        "retry": ["2h", "next 11:00"],
        # enabled = website/ads/forms; manual = added by hand on Leads; imports = file uploads (paced by per_run)
        "speed_to_lead": {"enabled": True, "manual": True, "imports": True, "per_run": 3},
        "handoff": {"sales_whatsapp": "", "crm_webhook": ""},
    }


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def current() -> dict:
    return _cfg or defaults()


def questions() -> dict:
    return current()["questions"]


def _apply(cfg: dict) -> None:
    """Push settings into the modules that use them."""
    global _cfg, version
    if cfg == _cfg:
        return
    _cfg = cfg
    version += 1
    from . import callbacks, scoring
    scoring._OVERRIDE = cfg.get("scoring")
    callbacks.OPEN_HOUR = int(cfg["calling_hours"]["start"])
    callbacks.CLOSE_HOUR = int(cfg["calling_hours"]["end"])
    callbacks.RETRY_STEPS = list(cfg.get("retry") or [])


async def ensure(http: httpx.AsyncClient) -> dict:
    """Load settings if the cached copy is older than 30 s (Redis first, then the database)."""
    global _loaded_at
    if _cfg is not None and time.monotonic() - _loaded_at < TTL_S:
        return _cfg
    stored = None
    if cache.enabled():
        try:
            raw = await cache._cmd(http, "GET", REDIS_KEY)
            stored = json.loads(raw) if raw else None
        except Exception:  # noqa: BLE001
            stored = None
    if stored is None:
        try:
            rows = await Supabase(http).select("campaigns", {"select": "settings", "id": f"eq.{settings().campaign_id}"})
            stored = (rows[0].get("settings") if rows else None) or {}
            if cache.enabled():
                await cache._cmd(http, "SET", REDIS_KEY, json.dumps(stored), "EX", 3600)
        except Exception:  # noqa: BLE001 — keep working on defaults if the database is unreachable
            stored = {}
    _apply(_merge(defaults(), stored))
    _loaded_at = time.monotonic()
    return _cfg


RETRY_RE = re.compile(r"^(\d{1,4})(m|h)$|^next (\d{1,2}):(\d{2})$")


def validate(cfg: dict) -> dict:
    """Clean and check user input from the Settings page; raises ValueError with a readable message."""
    out = _merge(defaults(), cfg)
    for k, q in out["questions"].items():
        for lang in ("en", "hi"):
            t = re.sub(r"\s+", " ", str(q.get(lang) or "")).strip()
            if not 3 <= len(t) <= 400:
                raise ValueError(f"Question '{k}' ({lang}) must be 3-400 characters.")
            q[lang] = t
    sc = out["scoring"]
    for k, p in sc.get("points", {}).items():
        p["max"] = int(p.get("max") or 0)
        p["partial"] = int(p.get("partial") or 0)
        if not (0 <= p["partial"] <= p["max"] <= 100):
            raise ValueError(f"Scoring '{k}': points must be 0-100 and partial ≤ max.")
    for k, v in (sc.get("tone") or {}).items():
        sc["tone"][k] = max(-50, min(20, int(v)))
    hot, warm = int(sc["tiers"]["hot"]), int(sc["tiers"]["warm"])
    if not 0 < warm < hot <= 100:
        raise ValueError("Pass marks: Warm must be lower than Hot, both between 1 and 100.")
    sc["tiers"] = {"hot": hot, "warm": warm}
    sc["hot_requires"] = [k for k in (sc.get("hot_requires") or []) if k in sc.get("points", {})]
    h = out["calling_hours"]
    h["start"], h["end"] = int(h["start"]), int(h["end"])
    if not 0 <= h["start"] < h["end"] <= 24:
        raise ValueError("Calling hours: start must be before end (0-24).")
    steps = [str(s).strip().lower() for s in out["retry"] if str(s).strip()]
    if len(steps) > 6 or any(not RETRY_RE.match(s) for s in steps):
        raise ValueError('Re-attempts: up to 6 steps like "10m", "2h" or "next 11:00".')
    out["retry"] = steps
    stl = out["speed_to_lead"]
    for k in ("enabled", "manual", "imports"):
        stl[k] = bool(stl.get(k))
    stl["per_run"] = max(1, min(10, int(stl.get("per_run") or 3)))
    wa = re.sub(r"[^\d+]", "", str(out["handoff"].get("sales_whatsapp") or ""))
    out["handoff"]["sales_whatsapp"] = wa[:16]
    url = str(out["handoff"].get("crm_webhook") or "").strip()
    if url and not re.match(r"^https://[^\s]{4,500}$", url):
        raise ValueError("CRM webhook must be an https:// address.")
    out["handoff"]["crm_webhook"] = url
    return out


async def save(http: httpx.AsyncClient, cfg: dict) -> dict:
    clean = validate(cfg)
    await Supabase(http).update("campaigns", {"id": f"eq.{settings().campaign_id}"}, {"settings": clean})
    if cache.enabled():
        try:
            await cache._cmd(http, "SET", REDIS_KEY, json.dumps(clean), "EX", 3600)
        except Exception:  # noqa: BLE001
            pass
    global _loaded_at
    _apply(clean)
    _loaded_at = time.monotonic()
    return clean
