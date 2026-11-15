"""End-to-end test of a full call through to the Property Expert call time (the PDF's CTA), no phone needed.

    python scripts/phone_cta_test.py            # live app
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

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend.settings import settings  # noqa: E402

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://vaani-divyasree.vercel.app").rstrip("/")
S = settings()
ok_all = True


def run(name: str, lines: list[str], expect_end: str) -> None:
    global ok_all
    sid = "CA" + uuid.uuid4().hex
    c = httpx.Client(timeout=30)

    def post(path: str, data: dict) -> str:
        url, data = BASE + path, {"CallSid": sid, "AccountSid": S.twilio_sid, "CallStatus": "in-progress", **data}
        sig = base64.b64encode(hmac.new(S.twilio_token.encode(), (url + "".join(k + data[k] for k in sorted(data))).encode(),
                                        hashlib.sha1).digest()).decode()
        for attempt in range(3):   # this laptop's connection sometimes drops; retry (the server is fine)
            try:
                return c.post(url, data=data, headers={"X-Twilio-Signature": sig}).text
            except httpx.TransportError:
                time.sleep(1)
        raise RuntimeError("no connection to the server")

    print(f"\n=== {name}")
    x = post("/api/phone/start?lead=", {"To": "+910000000000"})
    print("  DIVYA:", " ".join(re.findall(r"<Say[^>]*>(.*?)</Say>", x))[:110])
    said_before = []
    for line in lines:
        time.sleep(2.5)   # a real lead takes a few seconds (Divya speaks, then they answer)
        x = post("/api/phone/turn?lead=", {"SpeechResult": line})
        reply = " ".join(re.findall(r"<Say[^>]*>(.*?)</Say>", x))
        loop = reply in said_before
        said_before.append(reply)
        print(f"  LEAD : {line}\n  DIVYA: {reply[:150]}{'   <-- REPEATED' if loop else ''}{'   [call ends]' if '<Hangup' in x else ''}")
        if loop and "still there" not in reply:
            ok_all = False
        if "<Hangup" in x:
            break
    ended_ok = "<Hangup" in x and re.search(expect_end, reply, re.I)
    print(f"  {'PASS' if ended_ok else 'FAIL'}: call ends with {expect_end!r}")
    ok_all = ok_all and bool(ended_ok)


run("Lead gives the time after saying no once",
    ["Yes.", "Investment.", "Yes, the location is fine.", "Yes, that range works.", "Yes, December 2029 is fine.",
     "Just me.", "No.", "Can you tell me about the amenities?", "Tomorrow at 5 pm."],
    r"noted .*5 pm")
run("Lead never gives a time",
    ["Yes.", "Weekend home.", "Yes.", "Yes.", "Yes.", "My wife and I.", "No.", "No, nothing else.", "No."],
    r"reach out at a convenient time|have a (lovely|great|good|wonderful) day|thank you for your time")
print("\nALL PASS" if ok_all else "\nSOMETHING FAILED")
sys.exit(0 if ok_all else 1)
