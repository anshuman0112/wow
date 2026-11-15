"""Internal end-to-end test of a phone call, WITHOUT ringing anyone.

Sends the live server exactly what Twilio sends during a call (signed like Twilio), in order, then checks
every answer and the saved conversation:

    python scripts/phone_flow_test.py                       # against the live app
    python scripts/phone_flow_test.py http://127.0.0.1:8000  # against a local server

Uses the real sentences from test calls (including the ones that once broke the call).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import re
import sys
import uuid
from xml.dom import minidom

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import cache  # noqa: E402
from backend.settings import settings  # noqa: E402

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://vaani-divyasree.vercel.app").rstrip("/")
TOKEN = settings().twilio_token
SID = "CA" + uuid.uuid4().hex
results: list[tuple[bool, str]] = []


def sign(url: str, data: dict) -> str:
    raw = url + "".join(k + data[k] for k in sorted(data))
    return base64.b64encode(hmac.new(TOKEN.encode(), raw.encode(), hashlib.sha1).digest()).decode()


def says(xml: str) -> str:
    return " | ".join(re.findall(r"<Say[^>]*>(.*?)</Say>", xml)) or ("(hang up)" if "<Hangup" in xml else "(listening, silent)")


def valid(xml: str) -> bool:
    try:
        minidom.parseString(xml.encode())
        return True
    except Exception:  # noqa: BLE001
        return False


def check(ok: bool, label: str, detail: str = "") -> None:
    results.append((ok, label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}{(' | ' + detail) if detail else ''}")


async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as c:
        async def post(path: str, data: dict) -> tuple[int, str, str]:
            url, data = BASE + path, {"CallSid": SID, "AccountSid": settings().twilio_sid, **data}
            r = await c.post(url, data=data, headers={"X-Twilio-Signature": sign(url, data)})
            return r.status_code, r.text, r.headers.get("server-timing", "")

        async def lead(text: str) -> tuple[int, str, str]:
            return await post("/api/phone/turn?lead=", {"SpeechResult": text, "Confidence": "0.9"})

        st, x, srv = await post("/api/phone/start?lead=&stt=nova3", {"To": "+910000000000", "CallStatus": "in-progress"})
        check(st == 200 and valid(x) and 'speechModel="deepgram_nova-3"' in x and 'bargeIn="false"' in x
              and "partialResultCallback" not in x, "call starts: Nova-3, no barge-in, no early-answer", f"{srv} {says(x)[:60]}")

        st, x, srv = await lead("Yes.")
        check(st == 200 and "weekend home" in x, "'Yes.' -> intent question", f"{srv} {says(x)[:80]}")

        # From the call that went silent: this complete sentence was wrongly held back as 'unfinished'.
        st, x, srv = await lead("I am looking at it as a weekend home.")
        check(st == 200 and "<Say" in x, "complete answer is answered", f"{srv} {says(x)[:80]}")
        st, x, srv = await lead("Yes. It will work for me.")
        check(st == 200 and "<Say" in x, "'Yes. It will work for me.' is answered (was the silence bug)", f"{srv} {says(x)[:80]}")
        st, x, srv = await lead("And Yes. I'm fine with it.")
        check(st == 200 and "<Say" in x, "'And Yes. I'm fine with it.' is answered", f"{srv} {says(x)[:80]}")

        # A real cut-off sentence: keep listening, then join it with the rest.
        st, x, srv = await lead("Before going, can you please tell me when you")
        check(st == 200 and "<Say" not in x and "<Gather" in x, "cut off mid-sentence -> keeps listening", says(x))
        st, x, srv = await lead("will hand over the project?")
        check(st == 200 and "December 2029" in x, "...rest joined and answered (possession)", f"{srv} {says(x)[:80]}")

        # Cut off, then silence: must answer what was heard, NOT loop in silence (the old bug).
        st, x, srv = await lead("Can you tell me about the")
        check(st == 200 and "<Say" not in x, "cut off again -> keeps listening", says(x))
        st, x, srv = await post("/api/phone/turn?lead=&silence=1", {})
        check(st == 200 and "<Say" in x and "still there" not in x, "silence after a cut-off -> answers what it heard (no loop)",
              says(x)[:90])

        st, x, srv = await lead("The EMI plan and the loan")
        check(st == 200 and "EMI" in x and "upfront" in x, "EMI question answered properly", f"{srv} {says(x)[:90]}")
        st, x, srv = await lead("Can you please tell me what is the cost?")
        check(st == 200 and "ninety-two point four lakh" in x, "cost question answered", f"{srv} {says(x)[:90]}")

        st, x, srv = await post("/api/phone/turn?lead=&silence=1", {})
        check(st == 200 and "still there" in x, "silence -> 'Are you still there?'", says(x))
        st, x, srv = await lead("Yes, I am here. Saturday at 11 am works.")
        check(st == 200 and valid(x), "conversation continues after a silence", f"{srv} {says(x)[:90]}")

        r = await c.post(BASE + "/api/phone/partial?lead=", data={"CallSid": "CA" + uuid.uuid4().hex, "UnstableSpeechResult": "yes"})
        check(r.status_code == 403, "security: live words for an unknown call are rejected", str(r.status_code))

        async with httpx.AsyncClient(timeout=30) as h:
            row = await cache.get_session(h, SID)
        msgs = (row or {}).get("messages") or []
        dupes = [i for i in range(1, len(msgs)) if msgs[i]["role"] == msgs[i - 1]["role"]]
        check(bool(msgs) and not dupes and not (row or {}).get("raw", {}).get("pending"),
              "saved conversation is clean (no double answers, nothing stuck waiting)", f"{len(msgs)} lines")

    print(f"\n{sum(ok for ok, _ in results)}/{len(results)} checks passed")
    sys.exit(0 if all(ok for ok, _ in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
