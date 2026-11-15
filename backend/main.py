"""Vaani API — FastAPI app.

Runs on Vercel as a serverless Python function (api/index.py) and locally with:
    uvicorn backend.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
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
from .clients import TIMEOUT, Groq, ServiceError, Supabase
from .settings import settings

app = FastAPI(title="Vaani API", version="1.0.0",
              description="Backend for Vaani — the Divyasree outbound AI voice agent (Aanya).")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://vaani-divyasree.vercel.app", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"https://web-[a-z0-9-]+\.vercel\.app",
    allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"],
)


@app.middleware("http")
async def server_timing(request: Request, call_next):
    """Expose pure server processing time (excludes network to the caller) as a standard Server-Timing header."""
    import time
    t0 = time.perf_counter()
    response = await call_next(request)
    response.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - t0) * 1000:.0f}"
    return response


async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        yield client


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
    return {"phoneCalling": settings().phone_line != "none", "phoneLine": settings().phone_line}


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
    return await leads.import_leads(Supabase(http), req.leads)


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
    """Free trial: let anyone (e.g. a reviewer) verify their own number so Aanya can call it."""
    try:
        return await phone.verify_number(http, req.phone, req.name.strip(), req.location.strip())
    except phone.CallError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/phone/verify")
async def phone_verify_status(phone_number: str = Query(alias="phone", max_length=24),
                              http: httpx.AsyncClient = Depends(http_client)):
    return {"verified": await phone.is_verified(http, phone_number)}


# ── Phone conversation loop (free Twilio trial): Twilio speech ⇄ Python ⇄ Groq ──────
async def twilio_form(request: Request) -> dict[str, str]:
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
            else:
                print(f"[twilio] signature mismatch on {request.url.path} (signed url: {url})", flush=True)
                raise HTTPException(403, "bad Twilio signature")
    print(f"[twilio] {request.url.path} CallSid={params.get('CallSid', '')[-6:]} status={params.get('CallStatus')} "
          f"speech={params.get('SpeechResult', '')[:60]!r}", flush=True)
    return params


def _xml(content: str) -> Response:
    return Response(content=content.encode("utf-8"), media_type="text/xml; charset=utf-8")


@app.post("/api/phone/start")
async def phone_start(request: Request, lead: str = Query(default="", max_length=64),
                      http: httpx.AsyncClient = Depends(http_client)):
    form = await twilio_form(request)
    return _xml(await phone_agent.start(http, form.get("CallSid", ""), _uuid_or_blank(lead), form.get("To")))


@app.post("/api/phone/turn")
async def phone_turn(request: Request, lead: str = Query(default="", max_length=64), silence: int = 0,
                     http: httpx.AsyncClient = Depends(http_client)):
    form = await twilio_form(request)
    return _xml(await phone_agent.turn(http, form.get("CallSid", ""), _uuid_or_blank(lead),
                                       form.get("SpeechResult", ""), bool(silence)))


@app.post("/api/phone/status")
async def phone_status(request: Request, lead: str = Query(default="", max_length=64),
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
        if not res.get("finished") and lead_id:   # answered but never reached our start endpoint
            await Supabase(http).update("leads", {"id": f"eq.{lead_id}"}, {"status": "no_answer"})
        return res
    if status in ("no-answer", "busy", "failed", "canceled") and lead_id:
        await Supabase(http).update("leads", {"id": f"eq.{lead_id}"}, {"status": "no_answer"})
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
    line = ("Hello Anshuman, this is Aanya from Divyasree Developers, calling about Whispers of the Wind near "
            "Nandi Hills. Plots start at ninety-two point four lakh. Is this a good time for two minutes?")
    parts = []
    for n, v in enumerate(data()["phoneVoices"]["library"], 1):
        parts.append(phone_agent.says(f"Voice {n}. {line}", voice=v["id"]) + '<Pause length="1"/>')
    return _xml('<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(parts) + "</Response>")


@app.api_route("/api/twiml", methods=["GET", "POST"])
async def twiml(lead: str = Query(default="", max_length=64)):
    """Twilio fetches this when the lead answers: connect them to Aanya's SIP line."""
    lead = lead if re.fullmatch(r"[0-9a-fA-F-]{36}", lead) else ""
    return Response(content=phone.twiml_connect_to_aanya(lead), media_type="text/xml")


# ── Knowledge builder ────────────────────────────────────────────────────────
class KnowledgeRequest(BaseModel):
    text: str = Field(min_length=50, max_length=200_000)
    campaign_id: str = Field(default="divyasree-wow", max_length=64)


@app.post("/api/knowledge/build")
async def knowledge_build(req: KnowledgeRequest, http: httpx.AsyncClient = Depends(http_client)):
    return await knowledge.build_fact_sheet(Groq(http), Supabase(http), req.text, req.campaign_id)
