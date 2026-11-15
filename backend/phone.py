"""Real phone calls to a lead.

Two ways out, picked automatically:
  • vapi-number   — a paid number imported into Vapi (VAPI_PHONE_NUMBER_ID): Vapi dials the lead directly.
  • twilio-bridge — FREE Twilio trial: Twilio dials the lead, and when they answer our /api/twiml
                    endpoint tells Twilio to connect the call to Divya's free Vapi SIP line.
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote
from xml.sax.saxutils import escape

import httpx

from .clients import Supabase, Twilio, Vapi
from .settings import settings


class CallError(Exception):
    pass


def twiml_connect_to_aanya(lead_id: str = "") -> str:
    sip = settings().vapi_sip_uri + (f"?X-Lead-Id={quote(lead_id)}" if lead_id else "")
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<Response><Dial answerOnBridge="true" timeLimit="300"><Sip>{escape(sip)}</Sip></Dial></Response>')


async def call_lead(http: httpx.AsyncClient, lead_id: str, callback: bool = False) -> dict:
    s = settings()
    if s.phone_line == "none":
        raise CallError("No phone line configured: add Twilio keys (free bridge) or a Vapi phone number.")
    sb = Supabase(http)
    rows = await sb.select("leads", {"select": "id,name,phone,location,attempts,status,last_called_at", "id": f"eq.{lead_id}"})
    if not rows:
        raise CallError("Lead not found.")
    lead = rows[0]
    if lead["status"] == "do_not_call":
        raise CallError("This lead asked not to be called.")

    # Mark "calling" while we ask Twilio to dial (blocks double clicks). The attempt is only COUNTED once the
    # phone company actually accepts the call; if Twilio refuses (e.g. unverified number), nothing is counted.
    before = {"status": lead["status"], "last_called_at": lead.get("last_called_at")}
    await sb.update("leads", {"id": f"eq.{lead_id}"}, {
        "status": "calling", "last_called_at": datetime.now(timezone.utc).isoformat()})

    async def dialled() -> None:
        await sb.update("leads", {"id": f"eq.{lead_id}"}, {"attempts": (lead.get("attempts") or 0) + 1})
    from . import cache, voices
    lead["voice"] = await voices.selected(http)   # the voice chosen in the dashboard, read before dialling
    await cache.put_lead(http, lead)   # the call's first request reads it from Redis, not the database
    try:
        if s.phone_line == "vapi-number":
            first = (lead.get("name") or "").split(" ")[0]
            res = await Vapi(http).create_call({
                "assistantId": s.vapi_assistant_id, "phoneNumberId": s.vapi_phone_number_id,
                "customer": {"number": lead["phone"], **({"name": lead["name"]} if lead.get("name") else {})},
                "assistantOverrides": {"variableValues": {"name": first, "location": lead.get("location") or "", "lead_id": lead_id}},
                "metadata": {"lead_id": lead_id, "campaign_id": s.campaign_id}})
            await dialled()
            return {"ok": True, "via": "vapi-number", "id": res.get("id")}
        q = f"?lead={quote(lead_id)}" + ("&cb=1" if callback else "")   # cb=1: a scheduled call-back
        base = s.public_base_url
        if s.phone_line == "twilio-sip":      # paid Twilio: bridge into Vapi's SIP line
            url = f"{base}/api/twiml{q}"
        elif s.phone_line == "twilio-stream":  # live audio streaming (lowest latency), on the always-on server
            base = s.stream_base_url
            url = f"{base}/api/phone/stream-start{q}"
        else:                                 # free trial: Twilio speech + Python conversation loop
            url = f"{base}/api/phone/start{q}"
        res = await Twilio(http).call(lead["phone"], s.twilio_number, url, status_callback=f"{base}/api/phone/status{q}")
        await dialled()
        return {"ok": True, "via": s.phone_line, "id": res.get("sid")}
    except Exception as e:
        # The call never left: put the lead back exactly as it was (no fake "no answer", no fake attempt).
        await sb.update("leads", {"id": f"eq.{lead_id}"}, before)
        msg = str(e).lower()
        if any(x in msg for x in ("21219", "573002", "unverified", "verified recipient")):
            raise CallError("This number isn't verified on the free Twilio trial yet. Use \"Verify a number\" "
                            "on the Leads page first (takes 30 seconds).") from e
        raise CallError(str(e)) from e


async def verify_number(http: httpx.AsyncClient, raw_phone: str, name: str, location: str) -> dict:
    """Self-service for reviewers: make sure a number can receive calls on the free trial, and add it as a lead."""
    from . import cache
    from .leads import normalise_phone
    phone = normalise_phone(raw_phone)
    if not phone:
        raise CallError("Please enter a valid mobile number, e.g. 98765 43210 or +91 98765 43210.")
    sb, tw = Supabase(http), Twilio(http)
    await sb.upsert("leads", [{"name": name or None, "phone": phone, "location": location or None,
                               "source": "reviewer (verified)", "extra": {}}], "phone", ignore_duplicates=True)
    rows = await sb.select("leads", {"select": "id", "phone": f"eq.{phone}"})
    lead_id = rows[0]["id"] if rows else None
    if await tw.is_verified(phone):
        return {"verified": True, "phone": phone, "lead_id": lead_id}
    # Each verification makes Twilio ring the number: limit it (per number and overall) to stop abuse.
    if cache.enabled():
        for key, limit in ((f"verify:{phone}", 3), ("verify:all", 30)):
            try:
                n = await cache._cmd(http, "INCR", key)
                if n == 1:
                    await cache._cmd(http, "EXPIRE", key, 3600)
                if int(n) > limit:
                    raise CallError("Too many verification attempts. Please try again in an hour.")
            except httpx.HTTPError:
                pass
    try:
        code = await tw.start_verification(phone, name)
    except Exception as e:
        raise CallError(f"Twilio could not start verification: {str(e)[:160]}") from e
    return {"verified": False, "phone": phone, "lead_id": lead_id, "code": code}


async def is_verified(http: httpx.AsyncClient, raw_phone: str) -> bool:
    from .leads import normalise_phone
    phone = normalise_phone(raw_phone)
    return bool(phone) and await Twilio(http).is_verified(phone)
