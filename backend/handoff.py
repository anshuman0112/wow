"""Hand the buyer to the sales team: a profile, not a note.

After every call:
  • CRM webhook (Settings → Sales team hand-off): the full profile is POSTed automatically
  • Share on WhatsApp: a ready-to-send message (wa.me link, free; no paid WhatsApp API)
  • Download: a CSV of leads with score, objections, decision maker and next action

Real phone numbers are only released with the admin PIN (the dashboard itself shows masked numbers).
"""
from __future__ import annotations

import csv
import io
from urllib.parse import quote

import httpx

from .clients import Supabase

DECIDER = {"self": "Decides alone", "spouse": "Decides with spouse", "family": "Decides with family",
           "someone_else": "Someone else decides", "unknown": "Not known"}
CALL_FIELDS = ("vapi_call_id,lead_id,name,phone,started_at,duration_sec,language,summary,interest,score,score_breakdown,"
               "objections,decision_maker,next_action,callback_time,call_back_at,intent,geography_fit,budget_fit,timeline_fit")


async def load(sb: Supabase, call_key: str) -> tuple[dict, dict]:
    """A call (by id or vapi_call_id) and its lead, with real phone numbers (service key)."""
    flt = {"id": f"eq.{call_key}"} if len(call_key) == 36 and call_key.count("-") == 4 else {"vapi_call_id": f"eq.{call_key}"}
    call = (await sb.select("calls", {"select": CALL_FIELDS, **flt}) or [{}])[0]
    lead = {}
    if call.get("lead_id"):
        lead = (await sb.select("leads", {"select": "name,phone,location,budget,source,status", "id": f"eq.{call['lead_id']}"}) or [{}])[0]
    return call, lead


def profile(call: dict, lead: dict) -> dict:
    return {
        "name": call.get("name") or lead.get("name"), "phone": lead.get("phone") or call.get("phone"),
        "source": lead.get("source"), "city": lead.get("location"), "budget_stated": lead.get("budget"),
        "score": call.get("score"), "interest": call.get("interest"),
        "intent": call.get("intent"), "location_fit": call.get("geography_fit"), "budget_fit": call.get("budget_fit"),
        "timeline_fit": call.get("timeline_fit"), "decision_maker": call.get("decision_maker"),
        "objections": call.get("objections") or [], "next_action": call.get("next_action"),
        "expert_call": call.get("callback_time"), "call_back_at": call.get("call_back_at"),
        "summary": call.get("summary"), "called_at": call.get("started_at"), "call_id": call.get("vapi_call_id"),
        "project": "Whispers of the Wind (WOW) by Divyasree Developers",
    }


def text(p: dict) -> str:
    lines = [f"🏡 Whispers of the Wind lead: {p['name'] or 'Unknown'}",
             f"📞 {p['phone'] or '-'}" + (f" · {p['city']}" if p.get("city") else "") + (f" · via {p['source']}" if p.get("source") else ""),
             (f"⭐ Score {p['score']}/100 ({(p['interest'] or '').title()})" if p["score"] is not None
              else f"⭐ Interest: {p['interest'].title()}" if p.get("interest") else "")]
    lines += [f"• {label}: {p[k]}" for label, k in (("Intent", "intent"), ("Location", "location_fit"),
                                                   ("Budget", "budget_fit"), ("Timeline", "timeline_fit")) if p.get(k)]
    if p.get("decision_maker") and p["decision_maker"] != "unknown":
        lines.append(f"• {DECIDER.get(p['decision_maker'], p['decision_maker'])}")
    lines = [l for l in lines if l]
    if p["objections"]:
        lines.append("⚠️ Objections: " + "; ".join(p["objections"]))
    if p.get("expert_call"):
        lines.append(f"🗓️ Expert call: {p['expert_call']}")
    if p.get("next_action"):
        lines.append(f"➡️ Next: {p['next_action']}")
    return "\n".join(lines)


def whatsapp_url(message: str, sales_number: str) -> str:
    digits = "".join(c for c in sales_number or "" if c.isdigit())
    return f"https://wa.me/{digits}?text={quote(message)}" if digits else f"https://wa.me/?text={quote(message)}"


async def after_call(http: httpx.AsyncClient, call_key: str) -> str | None:
    """Automatic hand-off after every call: POST the profile to the CRM webhook from Settings (if set)."""
    from . import config_store
    url = (config_store.current().get("handoff") or {}).get("crm_webhook")
    if not url:
        return None
    sb = Supabase(http)
    call, lead = await load(sb, call_key)
    if not call:
        return None
    try:
        # Google Apps Script answers with a redirect after running doPost: follow it, and count it as delivered.
        r = await http.post(url, json={"event": "call.completed", "lead": profile(call, lead)},
                            timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=True)
        ok = r.is_success or r.is_redirect
        status = f"sent ({r.status_code})" if ok else f"failed ({r.status_code})"
    except httpx.HTTPError as e:
        status = f"failed ({type(e).__name__})"
    await sb.update("calls", {"vapi_call_id": f"eq.{call.get('vapi_call_id')}"}, {"crm_status": status})
    return status


async def export_csv(sb: Supabase, only: str = "") -> str:
    """Leads with their latest profile, ready for Excel or any CRM import."""
    params = {"select": "id,name,phone,location,budget,source,status,interest,score,decision_maker,next_action,"
                        "callback_time,last_called_at,attempts,created_at", "order": "score.desc.nullslast"}
    if only in ("hot", "warm", "cold"):
        params["interest"] = f"eq.{only}"
    leads = await sb.select("leads", params)
    calls = await sb.select("calls", {"select": "lead_id,objections,started_at", "order": "started_at.desc"})
    latest_obj: dict[str, list] = {}
    for c in calls:
        if c.get("lead_id") and c["lead_id"] not in latest_obj:
            latest_obj[c["lead_id"]] = c.get("objections") or []
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Name", "Phone", "City", "Budget stated", "Source", "Status", "Interest", "Score", "Decision maker",
                "Objections", "Next action", "Expert call", "Last called", "Calls dialled", "Added"])
    for l in leads:
        w.writerow([l.get("name") or "", l.get("phone") or "", l.get("location") or "", l.get("budget") or "",
                    l.get("source") or "", l.get("status") or "", l.get("interest") or "",
                    "" if l.get("score") is None else l["score"], DECIDER.get(l.get("decision_maker") or "", ""),
                    "; ".join(latest_obj.get(l["id"], [])), l.get("next_action") or "", l.get("callback_time") or "",
                    l.get("last_called_at") or "", l.get("attempts") or 0, l.get("created_at") or ""])
    return "﻿" + out.getvalue()   # BOM so Excel opens ₹ and Hindi text correctly
