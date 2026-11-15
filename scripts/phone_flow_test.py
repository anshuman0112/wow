"""Internal end-to-end test of a phone call, WITHOUT ringing anyone.

Sends the live server exactly what Twilio sends during a call (signed like Twilio), in the same order and
with the same races, then checks every answer and the saved conversation:

    python scripts/phone_flow_test.py                       # against the live app
    python scripts/phone_flow_test.py http://127.0.0.1:8000  # against a local server

Covers: call start, instant "yes" (live partial words), duplicate partials, Twilio's normal result for the
same "yes" (must not be answered twice), the race where both arrive together, a normal long answer, a
sentence cut off mid-way, the EMI question, silence, valid TwiML on every step, and server timings.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import re
import sys
import time
import uuid
from xml.dom import minidom

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import cache  # noqa: E402
from backend.settings import settings  # noqa: E402

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://vaani-divyasree.vercel.app").rstrip("/")
TOKEN = settings().twilio_token
SID = "CA" + uuid.uuid4().hex   # a fake call: only Twilio's "move the call" step can't succeed for it
results: list[tuple[bool, str]] = []


def sign(url: str, data: dict) -> str:
    raw = url + "".join(k + data[k] for k in sorted(data))
    return base64.b64encode(hmac.new(TOKEN.encode(), raw.encode(), hashlib.sha1).digest()).decode()


def says(xml: str) -> str:
    return " | ".join(re.findall(r"<Say[^>]*>(.*?)</Say>", xml)) or ("(hang up)" if "<Hangup" in xml else "(listening, silent)")


def check(ok: bool, label: str, detail: str = "") -> None:
    results.append((ok, label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}{(' | ' + detail) if detail else ''}")


async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as c:
        async def post(path: str, data: dict, signed: bool = True) -> tuple[int, str, float, str]:
            url, data = BASE + path, {"CallSid": SID, "AccountSid": settings().twilio_sid, **data}
            t = time.perf_counter()
            r = await c.post(url, data=data, headers={"X-Twilio-Signature": sign(url, data)} if signed else {})
            return r.status_code, r.text, (time.perf_counter() - t) * 1000, r.headers.get("server-timing", "")

        def valid(xml: str) -> bool:
            try:
                minidom.parseString(xml.encode())
                return True
            except Exception:  # noqa: BLE001
                return False

        st, x, ms, srv = await post("/api/phone/start?lead=&stt=nova3&instant=1", {"To": "+910000000000", "CallStatus": "in-progress"})
        check(st == 200 and valid(x) and "partialResultCallback" in x and 'speechModel="deepgram_nova-3"' in x
              and 'bargeIn="false"' in x, "call starts: Nova-3, instant mode, no barge-in", f"{srv} {says(x)[:70]}")

        # Twilio's live words while the lead talks (repeated about once a second until Twilio's own timer ends)
        async def partial(text: str) -> str:
            r = await c.post(BASE + "/api/phone/partial?lead=", data={"CallSid": SID, "UnstableSpeechResult": text})
            return f"{r.status_code} {r.text}"

        def fired(r: str) -> bool:
            return "answered" in r or "redirect-failed" in r

        async def started(n: int) -> str:   # Twilio fetches the instant reply (the call has moved)
            st, x, ms, srv = await post(f"/api/phone/next?n={n}", {})
            return says(x)

        # 1. From the real call: "Yeah…" then "…yes, it is a good time" must NOT be answered at "Yeah".
        r1 = await partial("Yeah")
        r2 = await partial("Yeah. Yes, it is a good time")
        check(not fired(r1) and not fired(r2), "never answers while the lead is still talking ('Yeah' -> 'Yeah, yes it is a good time')",
              f"{r1} / {r2}")
        t0 = time.perf_counter()
        r3 = await partial("Yeah. Yes, it is a good time.")
        ms3 = (time.perf_counter() - t0) * 1000
        check(fired(r3), "same words repeated (lead stopped) -> answered at once", f"{r3} in {ms3:.0f} ms (fake call: Twilio move fails, expected)")
        r4 = await partial("Yeah. Yes, it is a good time.")
        check("taken" in r4, "more repeats of the same words are not answered again", r4)
        first = await started(0)
        check("<" not in first and first != "(hang up)", "Twilio fetches the instant reply", first[:90])
        st, x, ms, srv = await post("/api/phone/turn?lead=", {"SpeechResult": "Yeah. Yes, it is a good time."})
        check(says(x) == first, "Twilio's own final result gets the SAME reply (no double answer)", says(x)[:60])

        # 2. A full question, answered as soon as it repeats (from the real call: the cost question).
        await partial("Can you please")
        await partial("Can you please tell me what is the cost")
        r = await partial("Can you please tell me what is the cost?")
        check(fired(r), "question answered as soon as the lead stops", r)
        x = await started(1)
        check("ninety-two point four lakh" in x, "...with the right answer (price)", x[:90])

        # 3. Unfinished sentence repeated (lead paused mid-sentence) is NOT answered early.
        await partial("Hi. Can you")
        r = await partial("Hi. Can you")
        check(not fired(r), "unfinished sentence ('Hi. Can you') is never answered early", r)

        # 4. Normal path still works when no early answer happens.
        st, x, ms, srv = await post("/api/phone/turn?lead=", {"SpeechResult": "Hi. Can you tell me about the EMI and loan?"})
        check(st == 200 and "EMI" in x, "normal path (no early answer): EMI question", f"{srv} {says(x)[:90]}")
        st, x, ms, srv = await post("/api/phone/turn?lead=", {"SpeechResult": "Before going, can you please tell me when you"})
        check(st == 200 and "<Say" not in x and "<Gather" in x, "cut off mid-sentence -> keeps listening silently", says(x))
        st, x, ms, srv = await post("/api/phone/turn?lead=", {"SpeechResult": "will hand over the project?"})
        check(st == 200 and "December 2029" in x, "...rest of the sentence is joined and answered", f"{srv} {says(x)[:90]}")

        # 5. Race: early answer and Twilio's final result arrive together -> one clean reply.
        await partial("It is for investment")
        r1, r2 = await asyncio.gather(partial("It is for investment."), post("/api/phone/turn?lead=", {"SpeechResult": "It is for investment."}))
        check(r2[0] == 200 and valid(r2[1]) and "once more" not in r2[1], "race: early + final together -> one clean reply",
              f"partial={r1} | turn says: {says(r2[1])[:70]}")

        st, x, ms, srv = await post("/api/phone/turn?lead=&silence=1", {})
        check(st == 200 and "still there" in x, "silence -> 'Are you still there?'", says(x))

        r = await c.post(BASE + "/api/phone/partial?lead=", data={"CallSid": "CA" + uuid.uuid4().hex, "UnstableSpeechResult": "yes"})
        check(r.status_code == 403, "security: live words for an unknown call are rejected", str(r.status_code))

        async with httpx.AsyncClient(timeout=30) as h:
            row = await cache.get_session(h, SID)
        msgs = (row or {}).get("messages") or []
        user = [m["text"] for m in msgs if m["role"] == "user"]
        dupes = [i for i in range(1, len(msgs)) if msgs[i]["role"] == msgs[i - 1]["role"]]
        check(bool(msgs) and not dupes, "saved conversation alternates cleanly (no double answers)",
              f"{len(msgs)} lines; lead said: {user}")

    print(f"\n{sum(ok for ok, _ in results)}/{len(results)} checks passed")
    sys.exit(0 if all(ok for ok, _ in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
