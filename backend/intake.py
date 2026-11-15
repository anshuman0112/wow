"""Lead intake: every lead source goes through here, then Divya calls within seconds.

    Website form (Enquire page) ─┐
    Facebook / Instagram ads ────┼─► intake() ─► clean number ─► duplicate check ─► save (with its source)
    Google Ads lead forms ───────┤                                            └─► speed to lead: call now
    Google Forms / any webhook ──┘                                                (or at the next calling window)

Sources (all free):
  • /api/leads/inbound  — website form, Google Forms, Typeform, any tool that can POST JSON
  • /api/leads/meta     — Facebook + Instagram Lead Ads (Meta webhook "leadgen"; same connection for both)
  • /api/leads/google   — Google Ads lead form webhook
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta, timezone

import httpx

from . import cache, callbacks
from .clients import Supabase
from .leads import duplicate_kind, normalise_phone
from .settings import settings

GRAPH = "https://graph.facebook.com/v21.0"


class IntakeError(Exception):
    pass


async def _limit(http: httpx.AsyncClient, key: str, max_per_hour: int) -> None:
    """Public endpoints: stop floods (per phone, per visitor, overall)."""
    if not cache.enabled():
        return
    try:
        n = int(await cache._cmd(http, "INCR", f"intake:{key}") or 0)
        if n == 1:
            await cache._cmd(http, "EXPIRE", f"intake:{key}", 3600)
    except Exception:  # noqa: BLE001
        return
    if n > max_per_hour:
        raise IntakeError("Too many submissions. Please try again later.")


def next_window_start(now: datetime) -> datetime:
    """Start of the next calling window (e.g. 9:00 IST) when a lead arrives after hours."""
    local = now.astimezone(callbacks.IST)
    start = local.replace(hour=callbacks.OPEN_HOUR, minute=0, second=0, microsecond=0)
    if local >= start:
        start += timedelta(days=1)
    return start.astimezone(timezone.utc)


async def intake(http: httpx.AsyncClient, lead: dict, source: str, *, client_ip: str = "") -> dict:
    """Save one incoming lead (no duplicates) and start the first call. Returns what happened, honestly."""
    from . import config_store, phone
    phone_no = normalise_phone(lead.get("phone"))
    if not phone_no:
        raise IntakeError("Please enter a valid mobile number.")
    await _limit(http, f"phone:{phone_no}", 3)
    if client_ip:
        await _limit(http, f"ip:{client_ip}", 20)
    await _limit(http, "all", 300)

    sb = Supabase(http)
    clip = lambda k, n=200: (str(lead.get(k)).strip()[:n] or None) if lead.get(k) not in (None, "") else None  # noqa: E731
    existing = (await sb.select("leads", {"select": "id,name,status,interest,attempts,notes", "phone": f"eq.{phone_no}"}) or [None])[0]
    now = datetime.now(timezone.utc)
    if existing:
        kind = duplicate_kind(existing)
        lead_id = existing["id"]
        if kind == "do_not_call":
            return {"lead_id": lead_id, "new": False, "duplicate": kind, "call": "not called (asked not to be called)"}
        if kind == "re_engaged":
            note = f"Re-enquired {now:%d %b %Y} via {source}"
            await sb.update("leads", {"id": f"eq.{lead_id}"}, {"status": "re_engaged", "re_engaged_at": now.isoformat(),
                            "notes": f"{existing['notes']} | {note}" if existing.get("notes") else note})
        elif kind in ("already_contacted", "already_listed"):
            return {"lead_id": lead_id, "new": False, "duplicate": kind,
                    "call": "not called again (already in your list)"}
    else:
        row = {"name": clip("name", 120), "phone": phone_no, "email": clip("email"), "location": clip("location"),
               "budget": clip("budget"), "notes": clip("notes", 500), "source": source[:60],
               "extra": lead.get("extra") if isinstance(lead.get("extra"), dict) else {},
               "campaign_id": settings().campaign_id, "status": "new"}
        saved = await sb.upsert("leads", [row], "phone", ignore_duplicates=True, returning=True)
        lead_id = (saved or await sb.select("leads", {"select": "id", "phone": f"eq.{phone_no}"}))[0]["id"]
        kind = None

    # Speed to lead: call right away (inside calling hours) or at the start of the next window.
    result = {"lead_id": lead_id, "new": existing is None, "duplicate": kind}
    if not config_store.current()["speed_to_lead"]["enabled"]:
        return result | {"call": "automatic calling is off (Settings → New leads)"}
    if not callbacks.is_calling_hours(now):
        at = next_window_start(now)
        await sb.update("leads", {"id": f"eq.{lead_id}"}, {"next_call_at": at.isoformat(),
                        "callback_note": f"arrived after hours, first call {callbacks.fmt_ist(at)}"})
        return result | {"call": f"scheduled for {callbacks.fmt_ist(at)} (outside calling hours)"}
    try:
        res = await phone.call_lead(http, lead_id)
        return result | {"call": "calling now", "call_id": res.get("id")}
    except phone.CallError as e:
        await sb.update("leads", {"id": f"eq.{lead_id}"}, {"callback_note": f"first call not possible: {str(e)[:150]}"})
        return result | {"call": "not called", "reason": str(e)}


# ── Facebook + Instagram Lead Ads (Meta) ────────────────────────────────────
def meta_signature_ok(body: bytes, header: str) -> bool:
    secret = os.environ.get("META_APP_SECRET", "")
    if not secret:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header or "")


def map_meta_fields(field_data: list[dict]) -> dict:
    """Meta lead form answers → our lead fields. Handles the standard questions + common custom ones."""
    f = {str(x.get("name", "")).lower(): ", ".join(x.get("values") or []) for x in field_data or []}
    pick = lambda *keys: next((f[k] for k in keys if f.get(k)), "")  # noqa: E731
    name = pick("full_name", "name") or " ".join(x for x in (pick("first_name"), pick("last_name")) if x)
    known = {"full_name", "name", "first_name", "last_name", "phone_number", "phone", "mobile", "email", "city",
             "location", "budget", "what_is_your_budget?", "message", "comments"}
    return {"name": name, "phone": pick("phone_number", "phone", "mobile"), "email": pick("email"),
            "location": pick("city", "location"), "budget": pick("budget", "what_is_your_budget?"),
            "notes": pick("message", "comments"), "extra": {k: v for k, v in f.items() if k not in known}}


async def meta_fetch_lead(http: httpx.AsyncClient, leadgen_id: str) -> tuple[dict, str]:
    """The webhook only carries an id: fetch the answers (and whether it came from Facebook or Instagram)."""
    token = os.environ.get("META_PAGE_TOKEN", "")
    if not token:
        raise IntakeError("META_PAGE_TOKEN is not set")
    r = await http.get(f"{GRAPH}/{leadgen_id}", params={"fields": "field_data,platform,created_time,form_id",
                                                         "access_token": token})
    if r.is_error:
        raise IntakeError(f"Meta API {r.status_code}: {r.text[:200]}")
    j = r.json()
    source = "Instagram" if str(j.get("platform", "")).lower() in ("ig", "instagram") else "Facebook"
    return map_meta_fields(j.get("field_data") or []), source


# ── Google Ads lead forms ───────────────────────────────────────────────────
def map_google_fields(body: dict) -> dict:
    cols = {str(c.get("column_id", "")).upper(): c.get("string_value", "") for c in body.get("user_column_data") or []}
    name = cols.get("FULL_NAME") or " ".join(x for x in (cols.get("FIRST_NAME"), cols.get("LAST_NAME")) if x)
    known = {"FULL_NAME", "FIRST_NAME", "LAST_NAME", "PHONE_NUMBER", "EMAIL", "CITY"}
    return {"name": name, "phone": cols.get("PHONE_NUMBER", ""), "email": cols.get("EMAIL", ""),
            "location": cols.get("CITY", ""), "extra": {k.lower(): v for k, v in cols.items() if k not in known}}


def google_key_ok(body: dict) -> bool:
    key = os.environ.get("GOOGLE_ADS_KEY", "")
    return bool(key) and hmac.compare_digest(str(body.get("google_key") or ""), key)


def sources_status() -> dict:
    """Which connectors are configured (for the Integrations page). Never returns the secrets themselves."""
    return {"website": True, "webhook": True,
            "meta": bool(os.environ.get("META_APP_SECRET") and os.environ.get("META_PAGE_TOKEN") and os.environ.get("META_VERIFY_TOKEN")),
            "meta_verify_ready": bool(os.environ.get("META_VERIFY_TOKEN")),
            "google": bool(os.environ.get("GOOGLE_ADS_KEY"))}


def clean_source(s: str) -> str:
    s = re.sub(r"[^\w\s/+.-]", "", str(s or "")).strip()
    return s[:40] or "Webhook"
