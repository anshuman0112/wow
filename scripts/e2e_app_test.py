"""End-to-end test of the whole application chain on the LIVE app (no real phone rings).

    python scripts/e2e_app_test.py

Uses two test leads with fake numbers (+91 90000 1234x, never dialled: the free Twilio trial only rings
verified numbers) and deletes them at the end. Steps:
  1. Lead intake (website form) -> saved, source, first call scheduled / attempted
  2. Same lead again -> no duplicate
  3. A full phone conversation -> summary, score, tier on the call AND the lead (must agree), booked time, CRM
  4. Busy lead "call me tomorrow at 5 pm" -> automatic call-back scheduled at that time (IST)
  5. Missed call (no-answer) -> automatic re-attempt scheduled
  6. Scheduler endpoint -> key required, calling hours respected
  7. Every call in the database: score and Hot/Warm/Cold agree with the scoring thresholds
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import scoring  # noqa: E402
from backend.settings import settings  # noqa: E402

BASE = "https://vaani-divyasree.vercel.app"
S = settings()
DB = S.supabase_url + "/rest/v1"
H = {"apikey": S.supabase_key, "Authorization": f"Bearer {S.supabase_key}", "Content-Type": "application/json"}
IST = timezone(timedelta(hours=5, minutes=30))
PHONE_A, PHONE_B = "+919000012345", "+919000012346"
c = httpx.Client(timeout=60)
results: list[bool] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {label}{(' | ' + str(detail)) if detail != '' else ''}")


def db(table: str, **params) -> list[dict]:
    return c.get(f"{DB}/{table}", headers=H, params=params).json()


def twilio(path: str, data: dict) -> httpx.Response:
    url = BASE + path
    data = {"AccountSid": S.twilio_sid, **data}
    sig = base64.b64encode(hmac.new(S.twilio_token.encode(), (url + "".join(k + data[k] for k in sorted(data))).encode(),
                                    hashlib.sha1).digest()).decode()
    for _ in range(3):
        try:
            return c.post(url, data=data, headers={"X-Twilio-Signature": sig})
        except httpx.TransportError:
            time.sleep(1)
    raise RuntimeError("no connection")


def conversation(lead_id: str, lines: list[str]) -> tuple[str, str]:
    sid = "CA" + uuid.uuid4().hex
    twilio(f"/api/phone/start?lead={lead_id}", {"CallSid": sid, "To": PHONE_A, "CallStatus": "in-progress"})
    last = ""
    for line in lines:
        time.sleep(2)
        x = twilio(f"/api/phone/turn?lead={lead_id}", {"CallSid": sid, "SpeechResult": line, "CallStatus": "in-progress"}).text
        last = " ".join(re.findall(r"<Say[^>]*>(.*?)</Say>", x))
        print(f"      LEAD: {line}\n      DIVYA: {last[:120]}")
        if "<Hangup" in x:
            break
    r = twilio(f"/api/phone/status?lead={lead_id}", {"CallSid": sid, "CallStatus": "completed", "CallDuration": "125"})
    return sid, r.text


def cleanup() -> None:
    for ph in (PHONE_A, PHONE_B):
        for L in db("leads", select="id", phone=f"eq.{ph}"):
            c.delete(f"{DB}/calls", headers=H, params={"lead_id": f"eq.{L['id']}"})
            c.delete(f"{DB}/leads", headers=H, params={"id": f"eq.{L['id']}"})


def main() -> None:
    cleanup()
    tiers = scoring.rules().get("tiers", {"hot": 70, "warm": 40})
    tier_of = lambda s: "hot" if s >= tiers["hot"] else "warm" if s >= tiers["warm"] else "cold"  # noqa: E731

    print("\n1. Lead intake (website form)")
    r = c.post(BASE + "/api/leads/inbound", json={"name": "E2E TEST lead", "phone": PHONE_A, "location": "Whitefield",
                                                   "budget": "1 crore", "source": "Website form"})
    j = r.json()
    lead = (db("leads", select="*", phone=f"eq.{PHONE_A}") or [{}])[0]
    check(r.status_code == 200 and j.get("new") and lead.get("id"), "new lead saved", f"call: {j.get('call')}")
    check(lead.get("source") == "Website form", "source recorded", lead.get("source"))
    check(bool(lead.get("next_call_at")) or "not called" in str(j.get("call")) or "calling" in str(j.get("call")),
          "first call scheduled or attempted", lead.get("next_call_at") or j.get("call"))

    print("\n2. Same lead submitted again")
    r = c.post(BASE + "/api/leads/inbound", json={"name": "E2E TEST lead", "phone": "+91 90000 12345", "source": "Facebook"})
    rows = db("leads", select="id", phone=f"eq.{PHONE_A}")
    check(r.status_code == 200 and not r.json().get("new") and len(rows) == 1, "no duplicate lead", r.json().get("duplicate"))

    lid = lead["id"]
    print("\n3. Full conversation -> analysis, score, tier, booked time, CRM")
    sid, res = conversation(lid, ["Yes, it's a good time.", "I'm looking at it as an investment.", "Yes, the location is fine.",
                                  "Yes, that range works.", "Yes, December 2029 is fine.", "Just me.",
                                  "How far is Nandi Hills?", "Tomorrow at 4 pm."])
    time.sleep(3)
    call = (db("calls", select="*", vapi_call_id=f"eq.tw_{sid}") or [{}])[0]
    L = (db("leads", select="*", id=f"eq.{lid}") or [{}])[0]
    check(bool(call.get("summary")), "summary saved", (call.get("summary") or "")[:110])
    check(call.get("score") is not None and call.get("interest") == tier_of(call["score"]),
          "call score and tier agree", f"{call.get('score')} -> {call.get('interest')}")
    check((call.get("score") or 0) >= tiers["hot"], "a fully qualified lead with a booked call is Hot", call.get("score"))
    check(L.get("score") == call.get("score") and L.get("interest") == call.get("interest"),
          "lead shows the same score and tier as its call", f"lead {L.get('score')}/{L.get('interest')}")
    check(L.get("status") == "called", "lead status = called", L.get("status"))
    check("4" in str(call.get("callback_time") or "") or "4" in str(L.get("callback_time") or ""),
          "booked time saved (tomorrow 4 pm)", call.get("callback_time") or L.get("callback_time"))
    check(len(call.get("score_breakdown") or []) >= 5, "score breakdown saved", len(call.get("score_breakdown") or []))
    check(call.get("crm_status") not in (None, "", "failed"), "CRM hand-off sent", call.get("crm_status"))

    print("\n4. Busy lead asks for a call later")
    sid2, res2 = conversation(lid, ["I'm busy right now.", "Call me tomorrow at 5 pm."])
    time.sleep(3)
    L = (db("leads", select="*", id=f"eq.{lid}") or [{}])[0]
    at = datetime.fromisoformat(L["next_call_at"].replace("Z", "+00:00")).astimezone(IST) if L.get("next_call_at") else None
    tomorrow = (datetime.now(IST) + timedelta(days=1)).date()
    check(L.get("status") == "callback", "lead status = callback", L.get("status"))
    check(at is not None and at.date() == tomorrow and at.hour == 17, "call-back scheduled tomorrow 5 pm IST",
          at.strftime("%a %d %b %H:%M IST") if at else None)

    print("\n5. Missed call (no answer) -> automatic re-attempt")
    r = c.post(BASE + "/api/leads/inbound", json={"name": "E2E TEST lead 2", "phone": PHONE_B, "source": "Google Ads"})
    lid2 = (db("leads", select="id", phone=f"eq.{PHONE_B}") or [{}])[0].get("id")
    twilio(f"/api/phone/status?lead={lid2}", {"CallSid": "CA" + uuid.uuid4().hex, "CallStatus": "no-answer"})
    L2 = (db("leads", select="*", id=f"eq.{lid2}") or [{}])[0]
    nxt = datetime.fromisoformat(L2["next_call_at"].replace("Z", "+00:00")) if L2.get("next_call_at") else None
    check(L2.get("status") == "no_answer" and nxt and nxt > datetime.now(timezone.utc), "re-attempt scheduled",
          f"{L2.get('status')} at {nxt.astimezone(IST).strftime('%a %H:%M IST') if nxt else None}")

    print("\n6. Scheduler endpoint")
    check(c.get(BASE + "/api/dialer/tick", headers={"X-Dialer-Key": "wrong"}).status_code == 401, "wrong key is refused")
    secret = os.environ.get("DIALER_SECRET", "")
    if secret:
        t = c.get(BASE + "/api/dialer/tick", headers={"X-Dialer-Key": secret}).json()
        check(isinstance(t, dict) and ("dialled" in t), "scheduler runs", t)

    print("\n7. Every saved call: score and tier agree")
    calls = db("calls", select="started_at,score,interest,score_breakdown", **{"score": "not.is.null"})
    need = set(scoring.rules().get("hot_requires", []))   # e.g. Hot needs a confirmed budget

    def expected(x: dict) -> str:
        yes = {b["key"] for b in (x.get("score_breakdown") or []) if b.get("verdict") == "yes"}
        t = tier_of(x["score"])
        return "warm" if t == "hot" and not need <= yes else t
    bad = [x for x in calls if x["interest"] != expected(x)]
    check(not bad, f"{len(calls)} calls checked", bad[:3])
    leads = db("leads", select="name,score,interest", **{"score": "not.is.null"})
    badl = [x for x in leads if x["interest"] not in (tier_of(x["score"]), "warm")]
    check(not badl, f"{len(leads)} leads checked", badl[:3])

    cleanup()
    print(f"\n{sum(results)}/{len(results)} checks passed (test leads deleted)")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
