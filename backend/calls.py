"""End-of-call processing: Vapi report → Supabase (call row, recording, lead update) → hot-lead alert."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone

import httpx

from .clients import Groq, Supabase, Vapi, telegram_alert
from .settings import settings

UUID = re.compile(r"^[0-9a-f-]{36}$", re.I)
NO_ANSWER = ("did-not-answer", "customer-busy", "voicemail", "failed-to-connect", "no-answer")


async def fetch_call_with_analysis(vapi: Vapi, call_id: str, attempts: int = 6) -> dict:
    """Vapi attaches the AI analysis a few seconds after the call ends — poll briefly for it."""
    call: dict = {}
    for i in range(attempts):
        try:
            call = await vapi.get_call(call_id)
        except Exception:  # noqa: BLE001
            call = call or {}
        if (call.get("artifact") or {}).get("structuredOutputs"):
            break
        await asyncio.sleep(2 if i < 3 else 3)
    return call


def _first(*vals):
    return next((v for v in vals if v not in (None, "", [], {})), None)


def build_row(msg: dict, call: dict) -> dict:
    """Combine the webhook report with the fetched call into one `calls` row (empty fields dropped)."""
    art = {**(msg.get("artifact") or {}), **(call.get("artifact") or {})}
    outputs = list((art.get("structuredOutputs") or {}).values())
    q = next((o.get("result") or {} for o in outputs if isinstance(o, dict) and o.get("name") == "Lead Qualification"), {})
    if not isinstance(q, dict):
        q = {}

    messages = [{"role": "user" if m.get("role") == "user" else "assistant",
                 "text": m.get("message") or m.get("content") or "", "t": m.get("secondsFromStart")}
                for m in (art.get("messages") or msg.get("messages") or []) if m.get("role") in ("bot", "assistant", "user")]
    transcript = art.get("transcript") or "\n".join(("Lead: " if m["role"] == "user" else "Divya: ") + m["text"] for m in messages)

    overrides = call.get("assistantOverrides") or {}
    variables = overrides.get("variableValues") or {}
    lead_id = _first((call.get("metadata") or {}).get("lead_id"), (overrides.get("metadata") or {}).get("lead_id"), variables.get("lead_id"))
    started, ended = _first(msg.get("startedAt"), call.get("startedAt")), _first(msg.get("endedAt"), call.get("endedAt"))
    duration = msg.get("durationSeconds")
    if duration is None and started and ended:
        duration = (datetime.fromisoformat(ended.replace("Z", "+00:00")) - datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds()

    row = {
        "vapi_call_id": _first(call.get("id"), (msg.get("call") or {}).get("id")),
        "lead_id": lead_id if lead_id and UUID.match(str(lead_id)) else None,
        "name": _first((call.get("customer") or {}).get("name"), variables.get("name")),
        "phone": (call.get("customer") or {}).get("number"),
        "call_type": call.get("type"),
        "started_at": started, "ended_at": ended, "duration_sec": duration,
        "ended_reason": _first(msg.get("endedReason"), call.get("endedReason")),
        "cost_usd": _first(msg.get("cost"), call.get("cost")),
        "transcript": transcript,
        "ai_lines": "\n".join(m["text"] for m in messages if m["role"] == "assistant"),
        "messages": messages,
        "summary": _first(q.get("summary"), (msg.get("analysis") or {}).get("summary")),
        "interest": q.get("interest") if q.get("interest") in ("hot", "warm", "cold") else None,
        "intent": q.get("intent"), "geography_fit": q.get("geography_fit"), "budget_fit": q.get("budget_fit"),
        "timeline_fit": q.get("timeline_fit"), "sentiment_start": q.get("sentiment_start"),
        "sentiment_end": q.get("sentiment_end"), "language": q.get("language"),
        "callback_time": q.get("callback_time"),
        "do_not_call": q.get("do_not_call") is True,
        "analysis": q, "raw": msg,
    }
    if q:   # score 0-100 + reasons, objections, decider, next action (same rules as phone calls)
        from . import scoring
        row |= scoring.profile_fields(q, scoring.rules())
    # Never overwrite saved data with blanks (e.g. if the Vapi fetch failed).
    return {k: v for k, v in row.items() if v not in (None, "", [], {})}


def recording_url(msg: dict, call: dict) -> str | None:
    """Vapi recordings live in a private bucket; only the presigned links (valid ~30 min) download."""
    art = {**(msg.get("artifact") or {}), **(call.get("artifact") or {})}
    return _first(art.get("presignedMonoUrl"), art.get("presignedStereoUrl"), art.get("recordingUrl"))


async def find_lead_for_bridged_call(sb: Supabase) -> str | None:
    """Phone calls through the free Twilio→SIP bridge arrive as inbound SIP calls without our lead id.
    The lead we just dialled is the one marked 'calling' in the last 10 minutes."""
    since = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    rows = await sb.select("leads", {"select": "id", "status": "eq.calling", "last_called_at": f"gte.{since}",
                                     "order": "last_called_at.desc", "limit": "1"})
    return rows[0]["id"] if rows else None


async def process_end_of_call(http: httpx.AsyncClient, msg: dict) -> dict:
    sb, vapi = Supabase(http), Vapi(http)
    call_id = (msg.get("call") or {}).get("id")
    if not call_id:
        return {"saved": False, "reason": "no call id"}

    call = await fetch_call_with_analysis(vapi, call_id)
    row = build_row(msg, call)
    if "lead_id" not in row and (call.get("type") or "").startswith("inbound"):
        lead_id = await find_lead_for_bridged_call(sb)
        if lead_id:
            row["lead_id"] = lead_id
    await sb.upsert("calls", row, "vapi_call_id")
    result = {"saved": True, "call_id": call_id, "interest": row.get("interest"), "lead_id": row.get("lead_id")}

    # Recording → Supabase Storage (permanent) + 1-year playback link
    url = recording_url(msg, call)
    if url:
        try:
            r = await http.get(url, timeout=httpx.Timeout(60.0, connect=25.0))
            r.raise_for_status()
            ext = (url.split("?")[0].rsplit(".", 1)[-1] or "mp3").lower()
            path = f"{call_id}.{ext}"
            await sb.upload("recordings", path, r.content, "audio/mpeg" if ext == "mp3" else "audio/wav")
            playback = await sb.signed_url("recordings", path, 31_536_000)
            await sb.update("calls", {"vapi_call_id": f"eq.{call_id}"}, {"storage_path": f"recordings/{path}", "recording_url": playback})
            result["recording"] = "saved"
        except Exception as e:  # noqa: BLE001 — the call row is already saved
            result["recording"] = f"failed: {type(e).__name__}: {e}"[:300]

    status = await apply_lead_update(sb, row, Groq(http))
    if status:
        result["lead_status"] = status
    if row.get("interest") == "hot":
        await telegram_alert(http, f"🔥 Hot lead: {row.get('name') or 'Caller'}\nCallback: {row.get('callback_time') or '—'}\n\n{row.get('summary') or ''}")
    return result


async def apply_lead_update(sb: Supabase, row: dict, groq: "Groq | None" = None) -> str | None:
    """After any call (browser or phone): set the lead's status, interest and callback time."""
    if not (row.get("lead_id") or row.get("phone")):
        return None
    reason = row.get("ended_reason") or ""
    no_answer = any(x in reason for x in NO_ANSWER)
    patch = {"status": "do_not_call" if row.get("do_not_call") else ("no_answer" if no_answer else "called"),
             "last_called_at": row.get("ended_at") or datetime.now(timezone.utc).isoformat()}
    if not no_answer:
        for k in ("interest", "callback_time", "score", "next_action", "decision_maker"):
            if row.get(k):
                patch[k] = row[k]
    filters = {"id": f"eq.{row['lead_id']}"} if row.get("lead_id") else {"phone": f"eq.{row['phone']}"}
    if not no_answer and groq is not None and patch["status"] != "do_not_call":
        # Busy lead who asked to be called back → schedule the automatic call-back.
        from . import callbacks
        lead = (await sb.select("leads", {"select": "callback_tries", **filters}) or [{}])[0]
        ended = datetime.fromisoformat(str(patch["last_called_at"]).replace("Z", "+00:00"))
        at, note = await callbacks.plan(groq, row.get("analysis") or {}, ended, lead.get("callback_tries") or 0)
        if at:
            patch |= {"status": "callback", "next_call_at": at.isoformat(), "callback_note": note}
            if row.get("vapi_call_id"):
                await sb.update("calls", {"vapi_call_id": f"eq.{row['vapi_call_id']}"}, {"call_back_at": at.isoformat()})
        else:
            patch |= {"next_call_at": None}
    await sb.update("leads", filters, patch)
    return patch["status"]
