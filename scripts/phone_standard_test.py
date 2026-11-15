"""Internal test of the STANDARD phone mode (what dashboard calls use), WITHOUT ringing anyone.

Standard mode = the original behaviour: Twilio's own speech recognition (speechTimeout="auto"), the lead can
talk over Divya (barge-in), and every result Twilio sends is answered right away (no extra waiting).

    python scripts/phone_standard_test.py                       # live app
    python scripts/phone_standard_test.py http://127.0.0.1:8000  # local server
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
S = settings()
SID = "CA" + uuid.uuid4().hex
results: list[bool] = []


def sign(url: str, data: dict) -> str:
    return base64.b64encode(hmac.new(S.twilio_token.encode(), (url + "".join(k + data[k] for k in sorted(data))).encode(),
                                     hashlib.sha1).digest()).decode()


def says(xml: str) -> str:
    return " | ".join(re.findall(r"<Say[^>]*>(.*?)</Say>", xml)) or "(no speech)"


def check(ok: bool, label: str, detail: str = "") -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {label}{(' | ' + detail) if detail else ''}")


async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as c:
        async def post(path: str, data: dict) -> tuple[int, str, str]:
            url, data = BASE + path, {"CallSid": SID, "AccountSid": S.twilio_sid, "CallStatus": "in-progress", **data}
            r = await c.post(url, data=data, headers={"X-Twilio-Signature": sign(url, data)})
            try:
                minidom.parseString(r.text.encode())
            except Exception:  # noqa: BLE001
                return 0, r.text, ""
            return r.status_code, r.text, r.headers.get("server-timing", "")

        async def lead(text: str):
            return await post("/api/phone/turn?lead=", {"SpeechResult": text, "Confidence": "0.9"})

        st, x, srv = await post("/api/phone/start?lead=", {"To": "+910000000000"})
        gather = re.search(r"<Gather[^>]*>", x).group(0)
        check(st == 200 and 'speechTimeout="auto"' in gather and 'bargeIn="true"' in gather and "speechModel" not in gather
              and "partialResultCallback" not in gather, "standard start: original settings (auto, barge-in on)", srv)
        for text, must, label in [
            ("Yes.", "weekend home", "'Yes.' -> intent question"),
            ("I'm looking at it as a weekend home.", "<Say", "intent answered"),
            ("Yes. I'm", "<Say", "short/cut result is answered right away (no extra waiting)"),
            ("Can you tell me about the amenities?", "clubhouse", "amenities question -> amenities answer"),
            ("The EMI plan and the loan", "upfront", "EMI -> EMI answer"),
            ("What is the price?", "ninety-two point four lakh", "price -> price answer"),
            ("When is the possession?", "2029", "possession -> possession answer"),
        ]:
            st, x, srv = await lead(text)
            check(st == 200 and must.lower() in x.lower() and "<Gather" in x, label, f"{srv} {says(x)[:90]}")
        st, x, srv = await post("/api/phone/turn?lead=&silence=1", {})
        check(st == 200 and "still there" in x, "silence -> 'Are you still there?'", says(x))
        st, x, srv = await lead("Saturday at 11 am.")
        check(st == 200 and "<Hangup" in x and "11" in x, "booking -> confirmed and call ends politely", says(x)[:90])

        async with httpx.AsyncClient(timeout=30) as h:
            row = await cache.get_session(h, SID) or {}
        msgs = row.get("messages") or []
        doubles = [i for i in range(1, len(msgs)) if msgs[i]["role"] == msgs[i - 1]["role"]]
        check(not doubles and not row.get("raw", {}).get("pending"), "conversation clean: no double answers, nothing waiting",
              f"{len(msgs)} lines")
    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
