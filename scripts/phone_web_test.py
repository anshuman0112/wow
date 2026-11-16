"""Internal test of WEB SEARCH on phone calls, WITHOUT ringing anyone.

A lead asks something the fact list can't answer ("How far is BTM Layout?", "Any malls nearby?"):
Divya says "let me quickly check", Twilio fetches /api/phone/search, Groq searches the web, Divya answers and
carries on with her next question. Asking the same thing again is answered instantly from the Redis cache.

    python scripts/phone_web_test.py                       # live app
    python scripts/phone_web_test.py http://127.0.0.1:8000  # local server
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
import uuid

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import cache  # noqa: E402
from backend.settings import settings  # noqa: E402
from phone_standard_test import sign, says  # noqa: E402

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://vaani-divyasree.vercel.app").rstrip("/")
S = settings()
SID = "CA" + uuid.uuid4().hex
results: list[bool] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {label}{(' | ' + detail) if detail else ''}", flush=True)


async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as c:
        async def post(path: str, data: dict) -> tuple[int, str, float]:
            url, data = BASE + path, {"CallSid": SID, "AccountSid": S.twilio_sid, "CallStatus": "in-progress", **data}
            t = time.perf_counter()
            r = await c.post(url, data=data, headers={"X-Twilio-Signature": sign(url, data)})
            return r.status_code, r.text, round(time.perf_counter() - t, 2)

        async def lead(text: str):
            return await post("/api/phone/turn?lead=", {"SpeechResult": text, "Confidence": "0.9"})

        await post("/api/phone/start?lead=", {"To": "+910000000000"})
        await lead("Yes.")
        for q, must in (("How far is BTM Layout from the project?", "sixty kilometres"), ("Is there any shopping mall nearby?", "mall"),
                        ("Is there a metro station close by?", "metro")):
            st, x, sec = await lead(q)
            check(st == 200 and must in x.lower() and "check that" not in x and "<Gather" in x,
                  f"{q!r} -> ready answer, no waiting", f"{sec}s {says(x)[:150]}")
        for q in ("Are there any good restaurants nearby?",):
            st, x, sec = await lead(q)
            redirect = re.search(r"<Redirect[^>]*>([^<]*/api/phone/search[^<]*)</Redirect>", x)
            instant = "<Gather" in x and "check that" not in x
            if instant:   # already in the 30-day cache
                check(st == 200, f"{q!r} -> answered instantly from the cache", f"{sec}s {says(x)[:160]}")
                continue
            check(st == 200 and "check that" in x and bool(redirect), f"{q!r} -> 'let me quickly check'", f"{sec}s")
            st, x, sec = await post("/api/phone/search?lead=", {})
            check(st == 200 and "<Gather" in x and "couldn't confirm" not in x and sec < 14,
                  f"web answer + next question (under Twilio's 15 s)", f"{sec}s {says(x)[:200]}")
            st, x, sec = await lead(q)
            check(st == 200 and "<Gather" in x and "check that" not in x and sec < 2,
                  "same question again -> instant answer from the cache", f"{sec}s {says(x)[:120]}")
        for q, must, label in [("How far is the airport?", "airport", "airport -> fact answer, no web search"),
                               ("How far is the railway station?", "railway", "railway station -> fact answer (not possession)"),
                               ("What is the EMI?", "", "EMI -> never searched on the web")]:
            st, x, sec = await lead(q)
            check(st == 200 and "check that" not in x and must in x.lower() and "<Gather" in x, label, f"{sec}s {says(x)[:120]}")

        async with httpx.AsyncClient(timeout=30) as h:
            row = await cache.get_session(h, SID) or {}
        msgs = row.get("messages") or []
        doubles = [i for i in range(1, len(msgs)) if msgs[i]["role"] == msgs[i - 1]["role"]]
        check(bool(msgs) and not doubles and not row.get("raw", {}).get("search"),
              "transcript clean: one Divya line per turn, nothing left waiting", f"{len(msgs)} lines")
        if doubles:
            for m in msgs:
                print("   ", m["role"], "|", m["text"][:100])
    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
