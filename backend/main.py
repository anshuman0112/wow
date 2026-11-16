"""WOW Voice Agent API — FastAPI app.

Runs on Vercel as a serverless Python function (api/index.py) and locally with:
    uvicorn backend.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import calls, knowledge, leads, phone, phone_agent, stream_agent
from .clients import TIMEOUT, Groq, ServiceError, Supabase, shared_client
from .settings import settings

app = FastAPI(title="WOW Voice Agent API", version="1.0.0",
              description="Backend for WOW Voice Agent — the Divyasree outbound AI voice agent (Divya).")


@app.middleware("http")
async def server_timing(request: Request, call_next):
    """Expose pure server processing time (excludes network to the caller) as a standard Server-Timing header."""
    import time
    t0 = time.perf_counter()
    if request.url.path.startswith("/api/"):
        # Settings page values (questions, scoring, hours, cadence…): refreshed at most every 30 s.
        from . import config_store
        await config_store.ensure(shared_client())   # reused connection: no new TLS handshake per request
    response = await call_next(request)
    response.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - t0) * 1000:.0f}"
    return response


@app.middleware("http")
async def require_sign_in(request: Request, call_next):
    """Every /api route needs a signed-in session, except the public ones (lead sources, Twilio, Vapi, scheduler)."""
    from . import auth
    path = request.url.path
    request.state.user = auth.verify(auth.bearer(request.headers))
    if (request.method != "OPTIONS" and path.startswith("/api/") and not auth.is_public(path)
            and auth.configured() and not request.state.user):
        return JSONResponse(status_code=401, content={"error": "sign in required"})
    return await call_next(request)


# Added last = outermost: answers browser pre-flight checks and adds CORS headers even to 401 answers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://vaani-divyasree.vercel.app", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"https://web-[a-z0-9-]+\.vercel\.app",
    allow_methods=["GET", "POST", "PUT", "OPTIONS"], allow_headers=["*"],
)


async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    # One long-lived connection pool per server instance (Groq, Redis, Supabase, Twilio connections stay
    # open between requests), instead of a new client + TLS handshakes on every phone turn.
    yield shared_client()


@app.exception_handler(ServiceError)
async def service_error(_: Request, e: ServiceError):
    return JSONResponse(status_code=502, content={"error": f"{e.service} failed", "status": e.status, "detail": e.detail[:300]})


@app.exception_handler(httpx.HTTPError)
async def network_error(_: Request, e: httpx.HTTPError):
    return JSONResponse(status_code=504, content={"error": "upstream unreachable", "detail": f"{type(e).__name__}: {e}"[:300]})


# ── Health & public config ───────────────────────────────────────────────────
@app.get("/api/health")
async def health(http: httpx.AsyncClient = Depends(http_client)):
    s = settings()
    from . import cache
    redis_ms = None
    if cache.enabled():
        import time
        t0 = time.perf_counter()
        try:
            await cache._cmd(http, "PING")
            redis_ms = round((time.perf_counter() - t0) * 1000)
        except httpx.HTTPError:
            redis_ms = -1
    import time as _t
    t0 = _t.perf_counter()
    try:
        await Supabase(http).select("campaigns", {"select": "id", "limit": "1"})
        supabase_ms = round((_t.perf_counter() - t0) * 1000)
    except Exception:  # noqa: BLE001
        supabase_ms = -1
    t0 = _t.perf_counter()
    try:
        await http.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {s.groq_key}"})
        groq_ms = round((_t.perf_counter() - t0) * 1000)
    except Exception:  # noqa: BLE001
        groq_ms = -1
    import os as _os
    return {"ok": True, "service": "vaani-api", "time": datetime.now(timezone.utc).isoformat(),
            "region": _os.environ.get("VERCEL_REGION", "local"),
            "redis": {"enabled": cache.enabled(), "ping_ms": redis_ms, "used_for_sessions": cache.fast_enough()},
            "supabase_ms": supabase_ms, "groq_ms": groq_ms,
            "configured": {"supabase": bool(s.supabase_url and s.supabase_key), "vapi": bool(s.vapi_key),
                           "groq": bool(s.groq_key), "phone_line": s.phone_line,
                           "webhook_secret": bool(s.vapi_webhook_secret)}}


@app.get("/api/config")
async def public_config():
    """What the dashboard needs to know (no secrets)."""
    import os
    return {"phoneCalling": settings().phone_line != "none", "phoneLine": settings().phone_line,
            "inboundNumber": os.environ.get("VAPI_INBOUND_NUMBER", "")}


@app.get("/api/stats/faq")
async def faq_stats(http: httpx.AsyncClient = Depends(http_client)):
    """Most-asked property questions on phone calls (counted in Redis)."""
    from . import cache, faq
    intents = list(faq.INTENTS)
    stats = await cache.faq_stats(http, intents)
    return {"redis": cache.enabled(), "most_asked": sorted(stats.items(), key=lambda kv: -kv[1])}


# ── Vapi webhook: end-of-call report ─────────────────────────────────────────
@app.post("/api/vapi/events")
async def vapi_events(request: Request, x_vapi_secret: str | None = Header(default=None),
                      http: httpx.AsyncClient = Depends(http_client)):
    secret = settings().vapi_webhook_secret
    if secret and not hmac.compare_digest(x_vapi_secret or "", secret):
        raise HTTPException(401, "bad webhook secret")
    body = await request.json()
    msg = body.get("message") or {}
    if msg.get("type") != "end-of-call-report":
        return {"ignored": msg.get("type")}
    return await calls.process_end_of_call(http, msg)


# ── Leads ────────────────────────────────────────────────────────────────────
class MapRequest(BaseModel):
    headers: list[str] = Field(max_length=200)
    sample: list[dict] = Field(default_factory=list, max_length=20)


@app.post("/api/leads/map")
async def leads_map(req: MapRequest, http: httpx.AsyncClient = Depends(http_client)):
    return {"mapping": await leads.ai_mapping(Groq(http), req.headers, req.sample)}


class ImportRequest(BaseModel):
    leads: list[dict] = Field(max_length=5000)


@app.post("/api/leads/import")
async def leads_import(req: ImportRequest, http: httpx.AsyncClient = Depends(http_client)):
    """Upload or hand-add leads; then (Settings → New leads) call them automatically: hand-added right away,
    uploaded ones paced by the scheduler. Duplicates already in the list are never called again."""
    from . import config_store, intake
    res = await leads.import_leads(Supabase(http), req.leads)
    ids = res.pop("_call_ids", [])
    stl = config_store.current()["speed_to_lead"]
    manual = bool(req.leads) and all(str(r.get("source") or "") == "added by hand" for r in req.leads)
    if ids and (stl["manual"] if manual else stl["imports"]):
        res["auto_call"] = await intake.auto_call_added(http, ids, immediate=manual)
    elif ids:
        res["auto_call"] = "automatic calling is off for these leads (Settings → New leads)"
    return res


# ── Real phone calls ─────────────────────────────────────────────────────────
class CallRequest(BaseModel):
    lead_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")


@app.post("/api/calls/now")
async def call_now(req: CallRequest, http: httpx.AsyncClient = Depends(http_client)):
    # Simple guard against double-clicks / abuse: one call per lead every 2 minutes.
    sb = Supabase(http)
    recent = await sb.select("leads", {"select": "id", "id": f"eq.{req.lead_id}", "status": "eq.calling",
                                       "last_called_at": f"gte.{(datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()}"})
    if recent:
        raise HTTPException(429, "This lead is already being called. Try again in 2 minutes.")
    try:
        return await phone.call_lead(http, req.lead_id)
    except phone.CallError as e:
        raise HTTPException(400, str(e)) from e


class VerifyRequest(BaseModel):
    phone: str = Field(min_length=6, max_length=24)
    name: str = Field(default="", max_length=80)
    location: str = Field(default="", max_length=80)


@app.post("/api/phone/verify")
async def phone_verify(req: VerifyRequest, http: httpx.AsyncClient = Depends(http_client)):
    """Free trial: let anyone (e.g. a reviewer) verify their own number so Divya can call it."""
    try:
        return await phone.verify_number(http, req.phone, req.name.strip(), req.location.strip())
    except phone.CallError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/phone/verify")
async def phone_verify_status(phone_number: str = Query(alias="phone", max_length=24),
                              http: httpx.AsyncClient = Depends(http_client)):
    return {"verified": await phone.is_verified(http, phone_number)}


# ── Lead sources: website form, Facebook/Instagram, Google Ads, any webhook ──
def _client_ip(request: Request) -> str:
    return (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or (request.client.host if request.client else "")


class InboundLead(BaseModel):
    name: str = Field(default="", max_length=120)
    phone: str = Field(min_length=6, max_length=24)
    email: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=120)
    budget: str = Field(default="", max_length=80)
    notes: str = Field(default="", max_length=500)
    source: str = Field(default="Website form", max_length=40)
    website: str = Field(default="", max_length=200)   # honeypot: real people never fill this hidden field


@app.post("/api/leads/inbound")
async def leads_inbound(req: InboundLead, request: Request, http: httpx.AsyncClient = Depends(http_client)):
    """Website form, Google Forms, Typeform or any tool: a new lead arrives → saved → Divya calls within seconds."""
    from . import intake
    if req.website:   # bot filled the hidden field
        return {"ok": True}
    try:
        res = await intake.intake(http, req.model_dump(exclude={"website", "source"}), intake.clean_source(req.source),
                                  client_ip=_client_ip(request))
    except intake.IntakeError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, **res}


@app.get("/api/leads/meta")
async def meta_verify(request: Request):
    """Meta checks the webhook once when you connect it: echo the challenge if the verify token matches."""
    import os
    q = request.query_params
    token = os.environ.get("META_VERIFY_TOKEN", "")
    if q.get("hub.mode") == "subscribe" and token and hmac.compare_digest(q.get("hub.verify_token", ""), token):
        return Response(content=q.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(403, "verify token mismatch")


@app.post("/api/leads/meta")
async def meta_leads(request: Request, http: httpx.AsyncClient = Depends(http_client)):
    """Facebook + Instagram Lead Ads: Meta sends the lead id the instant a form is submitted."""
    from . import intake
    body = await request.body()
    if not intake.meta_signature_ok(body, request.headers.get("x-hub-signature-256", "")):
        raise HTTPException(401, "bad Meta signature")
    payload = json.loads(body or b"{}")
    done = []
    for entry in payload.get("entry") or []:
        for ch in entry.get("changes") or []:
            if ch.get("field") != "leadgen":
                continue
            leadgen_id = str((ch.get("value") or {}).get("leadgen_id") or "")
            try:
                lead, source = await intake.meta_fetch_lead(http, leadgen_id)
                done.append({"leadgen_id": leadgen_id, **(await intake.intake(http, lead, source))})
            except intake.IntakeError as e:
                print(f"[meta] lead {leadgen_id}: {e}", flush=True)
                done.append({"leadgen_id": leadgen_id, "error": str(e)})
    return {"received": len(done), "leads": done}


@app.post("/api/leads/google")
async def google_leads(request: Request, http: httpx.AsyncClient = Depends(http_client)):
    """Google Ads lead form webhook (protected by the key you paste into Google Ads)."""
    from . import intake
    body = await request.json()
    if not intake.google_key_ok(body):
        raise HTTPException(401, "bad google_key")
    try:
        res = await intake.intake(http, intake.map_google_fields(body),
                                  "Google Ads (test)" if body.get("is_test") else "Google Ads")
    except intake.IntakeError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, **res}


# ── Live score during a browser call ─────────────────────────────────────────
class LiveScoreReq(BaseModel):
    messages: list[dict] = Field(max_length=80)


LIVE_FIELDS = ("intent", "geography_fit", "budget_fit", "timeline_fit", "decision_maker", "callback_time",
               "sentiment_end", "do_not_call", "evidence")


@app.post("/api/score/live")
async def live_score(req: LiveScoreReq, request: Request, http: httpx.AsyncClient = Depends(http_client)):
    """Score the conversation so far (same rules as the final profile). Talk page calls it after each lead turn."""
    from . import cache, scoring
    from .campaign import LEAD_ANALYSIS_OUTPUT
    if cache.enabled():   # protects the free AI quota
        key = f"livescore:{_client_ip(request)}"
        n = int(await cache._cmd(http, "INCR", key) or 0)
        if n == 1:
            await cache._cmd(http, "EXPIRE", key, 3600)
        if n > 120:
            raise HTTPException(429, "Live score limit reached for this hour.")
    msgs = [m for m in req.messages if str(m.get("text") or "").strip()][-40:]
    if not any(m.get("role") == "user" for m in msgs):
        return {"score": 0, "tier": "cold", "breakdown": [], "hot_blocked_by": []}
    transcript = "\n".join(("Lead: " if m.get("role") == "user" else "Divya: ") + str(m["text"])[:400] for m in msgs)
    props = LEAD_ANALYSIS_OUTPUT["schema"]["properties"]
    desc = "\n".join(f"- {k}: {props[k].get('description', '')}{' One of ' + str(props[k]['enum']) if 'enum' in props[k] else ''}"
                     for k in LIVE_FIELDS if k in props)
    try:
        q = await Groq(http).chat_json([
            {"role": "system", "content": "You score an IN-PROGRESS real-estate sales call. Use 'Not discussed' for anything "
                                          "not talked about yet. Reply with JSON only, with these fields:\n" + desc},
            {"role": "user", "content": transcript}], max_tokens=350)
    except Exception:  # noqa: BLE001 — a missed live update is fine; the final profile is computed after the call
        raise HTTPException(503, "Live score unavailable right now") from None
    return scoring.compute(q, scoring.rules())


# ── Hand-off to the sales team ───────────────────────────────────────────────
def _require_pin(x_admin_pin: str | None) -> None:
    pin = _admin_pin()
    if pin and not hmac.compare_digest((x_admin_pin or "").strip(), pin):
        raise HTTPException(401, "Wrong admin PIN.")


@app.get("/api/handoff/lead/{lead_id}")
async def handoff_lead(lead_id: str, http: httpx.AsyncClient = Depends(http_client)):
    """WhatsApp message for a lead from the Leads page: their latest call's profile, or their details if not called yet."""
    from . import config_store, handoff
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", lead_id):
        raise HTTPException(400, "bad lead id")
    sb = Supabase(http)
    last = await sb.select("calls", {"select": "vapi_call_id", "lead_id": f"eq.{lead_id}", "order": "started_at.desc", "limit": "1"})
    if last:
        call, lead = await handoff.load(sb, last[0]["vapi_call_id"])
    else:
        rows = await sb.select("leads", {"select": "name,phone,location,budget,source,status", "id": f"eq.{lead_id}"})
        if not rows:
            raise HTTPException(404, "Lead not found")
        call, lead = {"name": rows[0].get("name")}, rows[0]
    msg = handoff.text(handoff.profile(call, lead))
    if not last:
        msg += "\nℹ️ Not called yet." + (f" Budget stated: {lead['budget']}." if lead.get("budget") else "")
    return {"text": msg, "whatsapp_url": handoff.whatsapp_url(msg, config_store.current()["handoff"]["sales_whatsapp"])}


@app.get("/api/handoff/{call_key}")
async def handoff_message(call_key: str, x_admin_pin: str | None = Header(default=None),
                          http: httpx.AsyncClient = Depends(http_client)):
    """Ready-to-send profile for WhatsApp (real phone number included, so the admin PIN is required)."""
    from . import config_store, handoff
    _require_pin(x_admin_pin)
    call, lead = await handoff.load(Supabase(http), call_key[:80])
    if not call:
        raise HTTPException(404, "Call not found")
    msg = handoff.text(handoff.profile(call, lead))
    return {"text": msg, "whatsapp_url": handoff.whatsapp_url(msg, config_store.current()["handoff"]["sales_whatsapp"])}


@app.get("/api/export/leads.csv")
async def export_leads(only: str = Query(default="", max_length=10), x_admin_pin: str | None = Header(default=None),
                       http: httpx.AsyncClient = Depends(http_client)):
    from . import handoff
    _require_pin(x_admin_pin)
    body = await handoff.export_csv(Supabase(http), only)
    name = f"wow-leads{'-' + only if only else ''}-{datetime.now(timezone.utc):%Y%m%d}.csv"
    return Response(content=body.encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/handoff/echo")
async def handoff_echo_receive(request: Request, http: httpx.AsyncClient = Depends(http_client)):
    """Built-in test receiver for the CRM webhook: keeps the last payload for 10 minutes."""
    from . import cache
    body = (await request.body())[:20000].decode("utf-8", "replace")
    if cache.enabled():
        await cache._cmd(http, "SET", "handoff:echo", body, "EX", 600)
    return {"received": True}


@app.get("/api/handoff/echo/last")
async def handoff_echo_last(x_admin_pin: str | None = Header(default=None), http: httpx.AsyncClient = Depends(http_client)):
    from . import cache
    _require_pin(x_admin_pin)
    raw = await cache._cmd(http, "GET", "handoff:echo") if cache.enabled() else None
    return {"last": json.loads(raw) if raw else None}


class TestLead(BaseModel):
    phone: str = Field(default="+919000000999", max_length=24)
    name: str = Field(default="Test Lead", max_length=80)


@app.post("/api/leads/test/{source}")
async def lead_source_test(source: str, req: TestLead, x_admin_pin: str | None = Header(default=None),
                           http: httpx.AsyncClient = Depends(http_client)):
    """Integrations page 'Send test lead': a sample lead in each source's REAL format, through the same mapping
    and intake code the live connector uses. Admin PIN required."""
    from . import intake
    pin = _admin_pin()
    if pin and not hmac.compare_digest((x_admin_pin or "").strip(), pin):
        raise HTTPException(401, "Wrong admin PIN.")
    if source == "meta":   # what Meta returns for a lead (field_data), as Facebook or Instagram
        lead = intake.map_meta_fields([{"name": "full_name", "values": [req.name]}, {"name": "phone_number", "values": [req.phone]},
                                       {"name": "city", "values": ["Bengaluru"]}, {"name": "what_is_your_budget?", "values": ["1-1.5 crore"]}])
        label = "Facebook (test)"
    elif source == "instagram":
        lead = intake.map_meta_fields([{"name": "full_name", "values": [req.name]}, {"name": "phone_number", "values": [req.phone]},
                                       {"name": "city", "values": ["Hyderabad"]}])
        label = "Instagram (test)"
    elif source == "google":   # Google Ads lead form webhook body
        lead = intake.map_google_fields({"user_column_data": [{"column_id": "FULL_NAME", "string_value": req.name},
                                                              {"column_id": "PHONE_NUMBER", "string_value": req.phone},
                                                              {"column_id": "CITY", "string_value": "Pune"}]})
        label = "Google Ads (test)"
    elif source == "website":
        lead, label = {"name": req.name, "phone": req.phone, "location": "Chennai", "budget": "90 lakh - 1.2 crore"}, "Website form (test)"
    else:
        raise HTTPException(404, "Unknown source")
    try:
        return {"ok": True, "source": label, "mapped": {k: v for k, v in lead.items() if v}, **(await intake.intake(http, lead, label))}
    except intake.IntakeError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/leads/sources")
async def lead_sources(http: httpx.AsyncClient = Depends(http_client)):
    """Integrations page: which sources are connected, leads per source, last arrival, time to first call."""
    from . import intake
    rows = await Supabase(http).select("leads", {"select": "source,created_at,first_call_at"})
    by: dict[str, dict] = {}
    for r in rows:
        b = by.setdefault(r.get("source") or "unknown", {"leads": 0, "last": None, "speeds": []})
        b["leads"] += 1
        b["last"] = max(filter(None, [b["last"], r.get("created_at")]), default=None)
        if r.get("first_call_at") and r.get("created_at"):
            secs = (datetime.fromisoformat(r["first_call_at"].replace("Z", "+00:00")) -
                    datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))).total_seconds()
            if 0 <= secs < 86400 * 3:
                b["speeds"].append(secs)
    out = [{"source": k, "leads": v["leads"], "last_lead_at": v["last"],
            "avg_seconds_to_first_call": round(sum(v["speeds"]) / len(v["speeds"])) if v["speeds"] else None}
           for k, v in sorted(by.items(), key=lambda kv: -kv[1]["leads"])]
    return {"connected": intake.sources_status(), "by_source": out,
            "endpoints": {"website": "/enquire.html", "webhook": "/api/leads/inbound",
                          "meta": "/api/leads/meta", "google": "/api/leads/google"}}


# ── Automatic call-backs (busy leads) ────────────────────────────────────────
def _automation_key_ok(given: str | None) -> bool:
    """n8n and the GitHub scheduler send DIALER_SECRET; without it set, these endpoints stay closed (no data leak)."""
    import os
    secret = os.environ.get("DIALER_SECRET", "")
    return bool(secret) and hmac.compare_digest(given or "", secret)


@app.get("/api/automation/events")
async def automation_events(since: str = Query(default="", max_length=40), x_dialer_key: str | None = Header(default=None),
                            http: httpx.AsyncClient = Depends(http_client)):
    """Calls that finished after `since` (ISO time), for n8n's Hot-lead alert. Newest last."""
    if not _automation_key_ok(x_dialer_key):
        raise HTTPException(401, "bad automation key")
    try:
        after = datetime.fromisoformat(since.replace("Z", "+00:00")) if since else datetime.now(timezone.utc) - timedelta(minutes=15)
    except ValueError:
        raise HTTPException(400, "since must be an ISO date-time") from None
    rows = await Supabase(http).select("calls", {
        "select": "vapi_call_id,id,lead_id,name,phone,ended_at,duration_sec,score,interest,summary,intent,geography_fit,"
                  "budget_fit,timeline_fit,callback_time,next_action,objections",
        "ended_at": f"gt.{after.isoformat()}", "summary": "not.is.null", "order": "ended_at.asc", "limit": "50"})
    base = settings().public_base_url
    for r in rows:
        r["link"] = f"{base}/#/calls/{r.get('id') or r.get('vapi_call_id')}"
    return {"since": after.isoformat(), "calls": rows, "hot": [r for r in rows if r.get("interest") == "hot"]}


@app.get("/api/automation/report")
async def automation_report(x_dialer_key: str | None = Header(default=None), http: httpx.AsyncClient = Depends(http_client)):
    """Today's numbers (India time) for n8n's 7 pm email."""
    if not _automation_key_ok(x_dialer_key):
        raise HTTPException(401, "bad automation key")
    from . import callbacks
    ist = callbacks.IST
    start = datetime.now(ist).replace(hour=0, minute=0, second=0, microsecond=0)
    sb = Supabase(http)
    calls = await sb.select("calls", {"select": "name,interest,score,callback_time,duration_sec,ended_reason",
                                      "started_at": f"gte.{start.astimezone(timezone.utc).isoformat()}"})
    leads_new = await sb.select("leads", {"select": "id", "created_at": f"gte.{start.astimezone(timezone.utc).isoformat()}"})
    callbacks_due = await sb.select("leads", {"select": "name,next_call_at,status", "status": "eq.callback", "next_call_at": "not.is.null"})
    tiers = {t: sum(1 for c in calls if c.get("interest") == t) for t in ("hot", "warm", "cold")}
    booked = [{"name": c.get("name") or "Lead", "time": c["callback_time"]} for c in calls if c.get("callback_time")]
    mins = round(sum(float(c.get("duration_sec") or 0) for c in calls) / 60, 1)
    return {"date": start.strftime("%d %b %Y"), "calls": len(calls), "minutes": mins, **tiers, "expert_calls_booked": booked,
            "new_leads": len(leads_new),
            "call_backs_scheduled": [{"name": x.get("name"), "at": callbacks.fmt_ist(datetime.fromisoformat(x["next_call_at"].replace("Z", "+00:00")))}
                                     for x in callbacks_due]}


@app.api_route("/api/dialer/tick", methods=["GET", "POST"])
async def dialer_tick(key: str = Query(default="", max_length=128), x_dialer_key: str | None = Header(default=None),
                      http: httpx.AsyncClient = Depends(http_client)):
    """Called every few minutes by the scheduler: dial every lead whose call-back time has come.
    Safe to call any time: it only ever dials leads that are due, at most 3 per run, inside calling hours."""
    import os
    from . import callbacks, config_store
    secret = os.environ.get("DIALER_SECRET", "")
    if secret and not hmac.compare_digest(x_dialer_key or key, secret):
        raise HTTPException(401, "bad dialer key")
    now = datetime.now(timezone.utc)
    if not callbacks.is_calling_hours(now):
        return {"dialled": [], "reason": "outside calling hours (9 am - 9 pm IST)"}
    sb = Supabase(http)
    per_run = config_store.current()["speed_to_lead"]["per_run"]
    due = await sb.select("leads", {"select": "id,name,status,callback_tries", "status": "in.(callback,no_answer,new,re_engaged)",
                                    "next_call_at": f"lte.{now.isoformat()}", "order": "next_call_at.asc", "limit": str(per_run)})
    if len(due) < per_run and config_store.current()["speed_to_lead"]["enabled"]:
        # New leads that were never scheduled or dialled (e.g. added before automatic calling): call them too,
        # oldest first. A lead that can't be called gets a time far ahead, so it is never retried every minute.
        fresh = await sb.select("leads", {"select": "id,name,status,callback_tries", "status": "eq.new",
                                          "next_call_at": "is.null", "or": "(attempts.is.null,attempts.eq.0)",
                                          "order": "created_at.asc", "limit": str(per_run - len(due))})
        due += fresh
    done = []
    for lead in due:
        # Claim it first (clears the time) so two scheduler runs can never dial the same lead twice.
        is_callback = lead["status"] == "callback"   # else: a no-answer re-attempt
        from . import cache
        if not await cache.claim(http, f"dial:{lead['id']}", 120):   # another scheduler run (n8n / GitHub) has it
            continue
        claim = {"next_call_at": None}
        if is_callback:
            claim["callback_tries"] = (lead.get("callback_tries") or 0) + 1
        await sb.update("leads", {"id": f"eq.{lead['id']}", "status": f"eq.{lead['status']}"}, claim)
        try:
            res = await phone.call_lead(http, lead["id"], callback=is_callback)
            done.append({"lead": lead.get("name"), "ok": True, "kind": "call-back" if is_callback else "re-attempt",
                         "call": res.get("id")})
        except phone.CallError as e:
            # Not callable now (e.g. not verified on the free Twilio trial): note why and park it for 30 days
            # so the every-minute scheduler doesn't try it again and again. "Call now" still works any time.
            parked = (now + timedelta(days=30)).isoformat()
            await sb.update("leads", {"id": f"eq.{lead['id']}"}, {"callback_note": f"automatic call failed: {str(e)[:120]}",
                                                                  "next_call_at": parked})
            done.append({"lead": lead.get("name"), "ok": False, "error": str(e)[:160]})
    return {"dialled": done, "checked_at": now.isoformat()}


# ── Phone conversation loop (free Twilio trial): Twilio speech ⇄ Python ⇄ Groq ──────
async def twilio_form(request: Request, live_call_ok: bool = False) -> dict[str, str]:
    """Parse Twilio's form POST and verify X-Twilio-Signature (proves the request came from Twilio)."""
    body = (await request.body()).decode()
    params = {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}
    s = settings()
    if s.twilio_check_signature and s.twilio_token:
        tail = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        bases = {s.public_base_url, s.stream_base_url, f"https://{host}"} - {"", "https://"}
        # Twilio signs the URL either with or without the default port (like its official validator, accept both).
        candidates = [b + tail for b in bases] + [b + ":443" + tail for b in bases]
        url = f"{s.public_base_url}{tail}"
        given = request.headers.get("x-twilio-signature", "")
        body_part = "".join(k + params[k] for k in sorted(params))
        ok = any(hmac.compare_digest(
            base64.b64encode(hmac.new(s.twilio_token.encode(), (u + body_part).encode(), hashlib.sha1).digest()).decode(), given)
            for u in candidates)
        if not ok:
            # Fallback: genuine Twilio requests always carry our Account SID. Log loudly so it can be tightened.
            if params.get("AccountSid") == s.twilio_sid:
                print(f"[twilio] WARN signature mismatch on {request.url.path} but AccountSid matches — accepted. "
                      f"keys={sorted(params)} url={url}", flush=True)
            elif live_call_ok and params.get("CallSid") and await _is_live_call(params["CallSid"]):
                pass   # live-speech updates for a call in progress (its unguessable CallSid has an open session)
            else:
                print(f"[twilio] signature mismatch on {request.url.path} (signed url: {url})", flush=True)
                raise HTTPException(403, "bad Twilio signature")
    print(f"[twilio] {request.url.path} CallSid={params.get('CallSid', '')[-6:]} status={params.get('CallStatus')} "
          f"speech={params.get('SpeechResult', '')[:60]!r}", flush=True)
    return params


async def _is_live_call(call_sid: str) -> bool:
    from . import cache
    return bool(re.fullmatch(r"CA[0-9a-f]{32}", call_sid)) and bool(await cache.get_session(shared_client(), call_sid))


def _xml(content: str) -> Response:
    return Response(content=content.encode("utf-8"), media_type="text/xml; charset=utf-8")


@app.post("/api/phone/start")
async def phone_start(request: Request, lead: str = Query(default="", max_length=64), cb: int = 0,
                      http: httpx.AsyncClient = Depends(http_client)):
    form = await twilio_form(request)
    return _xml(await phone_agent.start(http, form.get("CallSid", ""), _uuid_or_blank(lead), form.get("To"),
                                        callback=bool(cb), stt=request.query_params.get("stt"),
                                        voice_override=request.query_params.get("voice"),
                                        instant=(request.query_params.get("instant") == "1") or None))


@app.post("/api/phone/turn")
async def phone_turn(request: Request, lead: str = Query(default="", max_length=64), silence: int = 0,
                     http: httpx.AsyncClient = Depends(http_client)):
    form = await twilio_form(request)
    return _xml(await phone_agent.turn(http, form.get("CallSid", ""), _uuid_or_blank(lead),
                                       form.get("SpeechResult", ""), bool(silence)))


@app.post("/api/phone/search")
async def phone_search(request: Request, lead: str = Query(default="", max_length=64),
                       http: httpx.AsyncClient = Depends(http_client)):
    """Right after Divya says "let me quickly check": Groq searches the web, Divya answers and carries on."""
    form = await twilio_form(request)
    return _xml(await phone_agent.web_turn(http, form.get("CallSid", ""), _uuid_or_blank(lead)))


@app.post("/api/phone/partial")
async def phone_partial(request: Request, lead: str = Query(default="", max_length=64),
                        http: httpx.AsyncClient = Depends(http_client)):
    """Live words while the lead is speaking (Gather partialResultCallback): a plain "yes" is answered at once."""
    form = await twilio_form(request, live_call_ok=True)
    heard = form.get("UnstableSpeechResult") or form.get("StableSpeechResult") or ""
    print(f"[instant] partial heard={heard[:40]!r} keys={sorted(form)}", flush=True)
    return {"result": await phone_agent.partial(http, form.get("CallSid", ""), _uuid_or_blank(lead), heard)}


@app.post("/api/phone/next")
async def phone_next(request: Request, n: int = 0, http: httpx.AsyncClient = Depends(http_client)):
    """Where an instantly-answered call is moved to: the reply prepared by /api/phone/partial."""
    from . import cache
    form = await twilio_form(request, live_call_ok=True)
    sid = form.get("CallSid", "")
    xml, _ = await asyncio.gather(cache.get_text(http, f"next:{sid}:{n}"), cache.put_text(http, f"fetched:{sid}:{n}", "1"))
    return _xml(xml or '<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>')


@app.post("/api/phone/recording")
async def phone_recording(request: Request, http: httpx.AsyncClient = Depends(http_client)):
    """Twilio finished recording a call: store the MP3 in Supabase Storage and link it to the call."""
    from . import cache
    from .clients import Twilio
    form = await twilio_form(request)
    sid, rec_url = form.get("CallSid", ""), form.get("RecordingUrl", "")
    if not (sid and rec_url and form.get("RecordingStatus", "completed") == "completed"):
        return {"saved": False, "reason": form.get("RecordingStatus")}
    r = await http.get(rec_url + ".mp3", auth=Twilio(http).auth, timeout=httpx.Timeout(60.0, connect=10.0),
                       follow_redirects=True)
    if r.is_error:
        return {"saved": False, "reason": f"download {r.status_code}"}
    sb = Supabase(http)
    path = f"twilio/{sid}.mp3"
    await sb.upload("recordings", path, r.content, "audio/mpeg")
    link = await sb.signed_url("recordings", path, 31_536_000)   # 1-year playback link
    patch = {"recording_url": link, "storage_path": f"recordings/{path}"}
    await sb.update("calls", {"vapi_call_id": f"eq.tw_{sid}"}, patch)
    await cache.put_text(http, f"rec:{sid}", link, 3600)   # in case the call row is written after this
    print(f"[recording] saved {sid[-6:]} {len(r.content) // 1024} KB", flush=True)
    return {"saved": True, "kb": len(r.content) // 1024}


@app.post("/api/phone/status")
async def phone_status(request: Request, lead: str = Query(default="", max_length=64), cb: int = 0,
                       http: httpx.AsyncClient = Depends(http_client)):
    """Twilio reports the call ended (hang-up, no answer, busy…): analyse + save, or mark no-answer."""
    form = await twilio_form(request)
    status, sid = form.get("CallStatus", ""), form.get("CallSid", "")
    lead_id = _uuid_or_blank(lead)
    if status == "completed":
        live = stream_agent.LIVE.get(sid)
        if live:   # streaming call: let the WebSocket save the final conversation first
            try:
                await asyncio.wait_for(live.closed.wait(), timeout=8)
            except asyncio.TimeoutError:
                pass
        res = await phone_agent.finish(http, sid, duration=float(form.get("CallDuration") or 0) or None)
        if not res.get("finished") and lead_id:   # picked up but never reached Divya (e.g. hung up at the trial message)
            from . import callbacks
            res["reattempt"] = await callbacks.schedule_reattempt(Supabase(http), lead_id)
        return res
    if status in ("no-answer", "busy", "failed", "canceled") and lead_id and cb:
        # A scheduled call-back went unanswered: retry once after an hour (within the call-back limit).
        from . import callbacks
        sb = Supabase(http)
        lead_row = (await sb.select("leads", {"select": "callback_tries,status", "id": f"eq.{lead_id}"}) or [{}])[0]
        if lead_row.get("status") != "do_not_call" and (lead_row.get("callback_tries") or 0) < callbacks.MAX_CALLBACKS:
            at = callbacks.retry_after_no_answer()
            await sb.update("leads", {"id": f"eq.{lead_id}"}, {"status": "callback", "next_call_at": at.isoformat(),
                                                               "callback_note": "call-back not answered, trying once more"})
            return {"status": status, "retry_at": at.isoformat()}
    if status in ("no-answer", "busy", "failed", "canceled") and lead_id:
        # Rang but nobody picked up: re-attempt automatically (2 h, then next day 11 am, then stop).
        from . import callbacks
        return {"status": status, "reattempt": await callbacks.schedule_reattempt(Supabase(http), lead_id)}
    return {"status": status}


def _uuid_or_blank(v: str) -> str:
    return v if re.fullmatch(r"[0-9a-fA-F-]{36}", v or "") else ""


# ── Live streaming engine (low latency): Twilio Media Streams ⇄ WebSocket ────────
# Runs on an always-on server (uvicorn locally + tunnel, or Render); Vercel functions can't hold WebSockets.
@app.post("/api/phone/stream-start")
async def phone_stream_start(request: Request, lead: str = Query(default="", max_length=64)):
    form = await twilio_form(request)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    if request.query_params.get("probe") == "fork":   # diagnostic: one-way audio fork + Twilio voice
        from xml.sax.saxutils import quoteattr
        return _xml('<?xml version="1.0" encoding="UTF-8"?><Response><Start>'
                    f'<Stream url={quoteattr(f"wss://{host}/ws/twilio")}>'
                    f'<Parameter name="token" value="{stream_agent.call_token(form.get("CallSid", ""))}"/></Stream></Start>'
                    '<Say voice="Polly.Kajal-Neural">Probe. Please say something after the beep.</Say>'
                    '<Pause length="8"/><Say voice="Polly.Kajal-Neural">Probe finished. Thank you.</Say></Response>')
    return _xml(stream_agent.twiml_stream(f"wss://{host}/ws/twilio", form.get("CallSid", ""), _uuid_or_blank(lead)))


@app.websocket("/ws/twilio")
async def twilio_media_stream(ws: WebSocket):
    await stream_agent.handle(ws)


# ── ConversationRelay engine: Twilio does speech↔text, we stream the reply word by word ─────
@app.post("/api/phone/relay-start")
async def phone_relay_start(request: Request, lead: str = Query(default="", max_length=64), cb: int = 0,
                            http: httpx.AsyncClient = Depends(http_client)):
    from . import relay_agent
    form = await twilio_form(request)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    return _xml(await relay_agent.start(http, form.get("CallSid", ""), _uuid_or_blank(lead), f"wss://{host}/ws/relay",
                                        callback=bool(cb), minimal=request.query_params.get("minimal") == "1"))


@app.websocket("/ws/relay")
async def twilio_conversation_relay(ws: WebSocket):
    from . import relay_agent
    await relay_agent.handle(ws)


# ── Sign-in ─────────────────────────────────────────────────────────────────
class LoginReq(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


@app.post("/api/auth/login")
async def auth_login(req: LoginReq, request: Request, http: httpx.AsyncClient = Depends(http_client)):
    from . import auth, cache
    key = f"login_fail:{_client_ip(request)}"
    if cache.enabled() and int(await cache._cmd(http, "GET", key) or 0) >= 10:
        raise HTTPException(429, "Too many wrong attempts. Try again in 15 minutes.")
    res = auth.login(req.email, req.password)
    if not res:
        if cache.enabled():
            await cache._cmd(http, "INCR", key)
            await cache._cmd(http, "EXPIRE", key, 900)
        raise HTTPException(401, "Wrong email or password.")
    return res


@app.get("/api/auth/me")
async def auth_me(request: Request):
    return {"email": request.state.user}


# ── Dashboard data (behind the sign-in; the database is no longer readable with the public key) ──
@app.get("/api/data/leads")
async def data_leads(http: httpx.AsyncClient = Depends(http_client)):
    return await Supabase(http).select("leads_public", {"select": "*", "order": "created_at.desc"})


@app.get("/api/data/calls")
async def data_calls(http: httpx.AsyncClient = Depends(http_client)):
    return await Supabase(http).select("calls_public", {"select": "*", "order": "started_at.desc"})


# ── Settings page ───────────────────────────────────────────────────────────
@app.get("/api/settings")
async def get_settings():
    from . import callbacks, config_store
    cfg = config_store.current()
    return {"settings": cfg, "defaults": config_store.defaults(), "max_dials": callbacks.max_dials(),
            "pin_required": bool(_admin_pin())}


def _admin_pin() -> str:
    """The old admin PIN, only used when no sign-in is configured (signed-in users are admins)."""
    import os
    from . import auth
    return "" if auth.configured() else os.environ.get("ADMIN_PIN", "").strip()


@app.put("/api/settings")
async def put_settings(request: Request, x_admin_pin: str | None = Header(default=None),
                       http: httpx.AsyncClient = Depends(http_client)):
    """Save settings (admin PIN required). Also re-syncs the browser assistant's prompt with the new questions."""
    from . import cache, config_store
    pin = _admin_pin()
    if pin:
        fails_key = "settings:pin_fails"
        fails = int(await cache._cmd(http, "GET", fails_key) or 0) if cache.enabled() else 0
        if fails >= 10:
            raise HTTPException(429, "Too many wrong PINs. Try again in an hour.")
        if not hmac.compare_digest((x_admin_pin or "").strip(), pin):
            if cache.enabled():
                await cache._cmd(http, "INCR", fails_key)
                await cache._cmd(http, "EXPIRE", fails_key, 3600)
            raise HTTPException(401, "Wrong admin PIN.")
    body = await request.json()
    try:
        saved = await config_store.save(http, body.get("settings") or {})
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    synced = await _sync_browser_prompt(http)
    return {"saved": True, "settings": saved, "browser_assistant_synced": synced}


async def _sync_browser_prompt(http: httpx.AsyncClient) -> bool:
    """Put the new questions into the browser (Vapi) assistant too, so both channels ask the same thing."""
    from .campaign import render_prompt
    from .clients import Vapi
    s = settings()
    if not (s.vapi_key and s.vapi_assistant_id):
        return False
    try:
        h = {"Authorization": f"Bearer {s.vapi_key}"}
        a = (await http.get(f"{Vapi.BASE}/assistant/{s.vapi_assistant_id}", headers=h)).json()
        model = a.get("model") or {}
        msgs = model.get("messages") or [{"role": "system", "content": ""}]
        msgs[0] = {"role": "system", "content": render_prompt()}
        model["messages"] = msgs
        r = await http.patch(f"{Vapi.BASE}/assistant/{s.vapi_assistant_id}", headers=h, json={"model": model})
        import os
        inbound = os.environ.get("VAPI_INBOUND_ASSISTANT_ID", "")
        if inbound:   # the inbound line asks the same questions
            from .campaign import INBOUND_NOTE
            im = (await http.get(f"{Vapi.BASE}/assistant/{inbound}", headers=h)).json().get("model") or {}
            im["messages"] = [{"role": "system", "content": INBOUND_NOTE + render_prompt()}]
            await http.patch(f"{Vapi.BASE}/assistant/{inbound}", headers=h, json={"model": im})
        return r.is_success
    except httpx.HTTPError:
        return False


# ── Phone voice library (dashboard → Voices) ────────────────────────────────
@app.get("/api/voices/phone")
async def phone_voices(http: httpx.AsyncClient = Depends(http_client)):
    from . import voices
    return {"selected": await voices.selected(http), "library": voices.library(),
            "previewInBrowser": voices.preview_token(ttl=5) is not None}


class VoiceChoice(BaseModel):
    voice: str = Field(max_length=80)


@app.post("/api/voices/phone")
async def choose_phone_voice(req: VoiceChoice, http: httpx.AsyncClient = Depends(http_client)):
    from . import voices
    if not voices.valid(req.voice):
        raise HTTPException(400, "Unknown voice")
    return {"selected": await voices.choose(http, req.voice)}


@app.get("/api/voices/preview-token")
async def voice_preview_token():
    from . import voices
    token = voices.preview_token()
    if not token:
        raise HTTPException(503, "Browser preview is not configured (TWILIO_API_KEY / SECRET / TWIML_APP_SID).")
    return {"token": token}


@app.post("/api/twiml/voice-preview")
async def twiml_voice_preview(request: Request):
    """The browser ▶ Play 'call' lands here: speak the sample line in the requested library voice."""
    from . import voices
    form = await twilio_form(request)
    voice = form.get("voice", "")
    if not voices.valid(voice):
        voice = voices.default_voice()
    return _xml('<?xml version="1.0" encoding="UTF-8"?><Response>'
                + phone_agent.says(voices.SAMPLE, voice=voice) + "<Hangup/></Response>")


@app.api_route("/api/twiml/voice-demo", methods=["GET", "POST"])
async def twiml_voice_demo():
    """Audition call: every voice in the campaign's phone voice library reads the same line, numbered."""
    from .campaign import data
    line = ("Hello Anshuman, this is Divya from Divyasree Developers, calling about Whispers of the Wind near "
            "Nandi Hills. Plots start at ninety-two point four lakh. Is this a good time for two minutes?")
    parts = []
    for n, v in enumerate(data()["phoneVoices"]["library"], 1):
        parts.append(phone_agent.says(f"Voice {n}. {line}", voice=v["id"]) + '<Pause length="1"/>')
    return _xml('<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(parts) + "</Response>")


@app.api_route("/api/twiml", methods=["GET", "POST"])
async def twiml(lead: str = Query(default="", max_length=64)):
    """Twilio fetches this when the lead answers: connect them to Divya's SIP line."""
    lead = lead if re.fullmatch(r"[0-9a-fA-F-]{36}", lead) else ""
    return Response(content=phone.twiml_connect_to_aanya(lead), media_type="text/xml")


# ── Knowledge builder ────────────────────────────────────────────────────────
class KnowledgeRequest(BaseModel):
    text: str = Field(min_length=50, max_length=200_000)
    campaign_id: str = Field(default="divyasree-wow", max_length=64)


@app.post("/api/knowledge/build")
async def knowledge_build(req: KnowledgeRequest, http: httpx.AsyncClient = Depends(http_client)):
    return await knowledge.build_fact_sheet(Groq(http), Supabase(http), req.text, req.campaign_id)
