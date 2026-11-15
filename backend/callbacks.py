"""Automatic call-backs: the lead was busy and asked Divya to call back at a certain time.

    "I'm busy, call me tomorrow at 5"  →  analysis: lead_busy=true, call_back_request="tomorrow at 5"
                                      →  resolve(): 16 Nov 17:00 IST (exact time, India time)
                                      →  lead status "callback", next_call_at = that time
    every ~5 min the scheduler hits /api/dialer/tick → due leads are called with a call-back greeting

Rules that keep it polite (non-intrusive, as the brief asks):
  • only between 9 am and 9 pm IST (a time outside that moves to 10 am)
  • busy but no time given → one try about 3 hours later
  • at most MAX_CALLBACKS call-back calls per lead (an unanswered call-back is retried once after an hour)
  • "don't call me" always wins: nothing is ever scheduled for a do-not-call lead
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .clients import Groq

IST = timezone(timedelta(hours=5, minutes=30))
OPEN_HOUR, CLOSE_HOUR = 9, 21          # call-backs only between 9:00 and 21:00 IST
MAX_CALLBACKS = 2                      # call-back calls per lead, including the no-answer retry
DEFAULT_DELAY = timedelta(hours=3)     # busy, but no time given
RETRY_DELAY = timedelta(hours=1)       # call-back not answered


def polite(at: datetime) -> datetime:
    """Move a time into calling hours (IST)."""
    local = at.astimezone(IST)
    if local.hour < OPEN_HOUR:
        local = local.replace(hour=10, minute=0, second=0, microsecond=0)
    elif local.hour >= CLOSE_HOUR:
        local = (local + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    return local.astimezone(timezone.utc)


RESOLVE_SYSTEM = """You convert a spoken call-back request from an Indian phone call into an exact date and time.
Reply with JSON only: {"at": "YYYY-MM-DDTHH:MM"} in India time (IST), or {"at": null} if no time can be worked out.
Rules: "tomorrow"/"kal" = the next day. "after N hours/minutes" = relative to the call time. A day without a time = 11:00.
morning/subah = 10:30, afternoon/dopahar = 15:00, evening/shaam = 18:00, night/raat = 20:00, lunch = 14:00.
A bare hour like "5" or "5 baje" between 1 and 8 means PM. If the time today has already passed, use the next day.
Never return a time before the call time."""


async def resolve(groq: Groq, request: str, call_time: datetime) -> datetime | None:
    """'tomorrow 5 pm' (+ when the call happened) → exact UTC datetime, or None."""
    if not (request or "").strip():
        return None
    local = call_time.astimezone(IST)
    try:
        out = await groq.json_chat(RESOLVE_SYSTEM, f"Call time (IST): {local:%A %d %B %Y, %H:%M}\nLead said: {request}")
        at = datetime.fromisoformat(str(out.get("at") or "")).replace(tzinfo=IST)
    except Exception:  # noqa: BLE001 — unparseable → caller falls back to the default delay
        return None
    if not (call_time < at.astimezone(timezone.utc) < call_time + timedelta(days=14)):
        return None   # nonsense (past or far future): don't trust it
    return at.astimezone(timezone.utc)


async def plan(groq: Groq, analysis: dict, call_time: datetime, tries_so_far: int) -> tuple[datetime | None, str]:
    """When (if at all) Divya should call this lead back, and the note to show. (None, '') = no call-back."""
    if analysis.get("do_not_call") is True or tries_so_far >= MAX_CALLBACKS:
        return None, ""
    request = (analysis.get("call_back_request") or "").strip()
    busy = analysis.get("lead_busy") is True or bool(request)
    if not busy:
        return None, ""
    at = await resolve(groq, request, call_time) if request else None
    note = request or "busy, no time given"
    if at is None:
        at = call_time + DEFAULT_DELAY
        note = f"{note} (trying again in about 3 hours)" if not request else f"{note} (time unclear, trying in about 3 hours)"
    return polite(at), note[:200]


# Re-attempt cadence from the Settings page: one entry per retry. "10m" / "2h" = after that long,
# "next 11:00" = next day at 11:00 IST. After the last step the lead is marked unreachable.
RETRY_STEPS: list[str] = ["2h", "next 11:00"]


def max_dials() -> int:
    """First call + one per retry step."""
    return len(RETRY_STEPS) + 1


def _step_time(step: str, now: datetime) -> datetime | None:
    m = re.match(r"^(\d{1,4})(m|h)$", step.strip().lower())
    if m:
        n = int(m.group(1))
        return polite(now + (timedelta(minutes=n) if m.group(2) == "m" else timedelta(hours=n)))
    m = re.match(r"^next (\d{1,2}):(\d{2})$", step.strip().lower())
    if m:
        nxt = (now.astimezone(IST) + timedelta(days=1)).replace(hour=int(m.group(1)), minute=int(m.group(2)),
                                                                  second=0, microsecond=0)
        return polite(nxt.astimezone(timezone.utc))
    return None


def reattempt_at(dialled: int, now: datetime | None = None) -> datetime | None:
    """Rang but nobody picked up: when to try again (Settings → re-attempt cadence), or None = stop."""
    now = now or datetime.now(timezone.utc)
    if dialled < 1 or dialled >= max_dials():
        return None if dialled >= max_dials() else _step_time(RETRY_STEPS[0], now) if RETRY_STEPS else None
    return _step_time(RETRY_STEPS[dialled - 1], now)


async def schedule_reattempt(sb, lead_id: str) -> dict:
    """Mark a lead not reached and schedule the next try (or stop after the limit)."""
    lead = (await sb.select("leads", {"select": "attempts,status", "id": f"eq.{lead_id}"}) or [{}])[0]
    if lead.get("status") == "do_not_call":
        return {}
    dialled = lead.get("attempts") or 0
    at = reattempt_at(dialled)
    patch = {"status": "no_answer", "next_call_at": at.isoformat() if at else None,
             "callback_note": (f"no answer ({dialled} of {max_dials()} tries), re-attempt {fmt_ist(at)}" if at
                               else f"unreachable: no answer after {dialled} tries")}
    await sb.update("leads", {"id": f"eq.{lead_id}"}, patch)
    return patch


def is_calling_hours(now: datetime | None = None) -> bool:
    h = (now or datetime.now(timezone.utc)).astimezone(IST).hour
    return OPEN_HOUR <= h < CLOSE_HOUR


def retry_after_no_answer(now: datetime | None = None) -> datetime:
    return polite((now or datetime.now(timezone.utc)) + RETRY_DELAY)


def fmt_ist(at: datetime | str | None) -> str:
    if not at:
        return ""
    if isinstance(at, str):
        at = datetime.fromisoformat(at.replace("Z", "+00:00"))
    d = at.astimezone(IST)
    return f"{d.day} {d:%b}, {d.hour % 12 or 12}:{d:%M} {d:%p}"
