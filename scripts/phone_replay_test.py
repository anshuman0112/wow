"""Replays a real call (16 Nov, the lead's exact words) WITHOUT ringing anyone, and checks the two fixes:
- "How far is Nandi Hills?" gets a short answer about Nandi Hills only (not the whole location list)
- "Tomorrow, I…" -> Divya asks the time; "Tomorrow around 5PM." -> confirmed once and the call ends
  (no "When should our Property Expert call you?" after the confirmation)

    python scripts/phone_replay_test.py                       # live app
    python scripts/phone_replay_test.py http://127.0.0.1:8000  # local server
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import uuid

import httpx

sys.path.insert(0, os.path.dirname(__file__))
from phone_standard_test import S, sign, says  # noqa: E402

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://vaani-divyasree.vercel.app").rstrip("/")
SID = "CA" + uuid.uuid4().hex
results: list[bool] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {label}{(' | ' + detail) if detail else ''}", flush=True)


async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as c:
        async def post(path: str, data: dict) -> str:
            url, data = BASE + path, {"CallSid": SID, "AccountSid": S.twilio_sid, "CallStatus": "in-progress", **data}
            return (await c.post(url, data=data, headers={"X-Twilio-Signature": sign(url, data)})).text

        async def lead(text: str) -> str:
            return await post("/api/phone/turn?lead=", {"SpeechResult": text, "Confidence": "0.9"})

        await post("/api/phone/start?lead=", {"To": "+910000000000"})
        for text in ("Yes.", "I'm looking for both.", "Yes. I'm comfortable.",
                     "It will work for me for... But before, can you tell me what are amenities are there?"):
            await lead(text)
        x = await lead("Yes. And can you please tell me how far is Nandi Hills?")
        check("fifteen minutes" in x and "railway" not in x.lower() and "yelahanka" not in x.lower(),
              "'how far is Nandi Hills?' -> just Nandi Hills", says(x)[:160])
        x = await lead("Yes. It do work. And can you tell me the nearby school and how far is Nandi Hills?")
        said = says(x)
        check(said.find("fifteen minutes") != -1 and said.find("fifteen minutes") < said.find("GITAM") and "Columbia" not in said,
              "'nearby school and how far is Nandi Hills?' -> Nandi Hills first, then schools only", said[:200])
        await lead("No. No one will be the part of this decision. But can you tell me and help me with the EMI and loan process?")
        x = await lead("Tomorrow, I")
        check("what time" in x.lower() and "<Hangup" not in x, "'Tomorrow, I…' -> asks for the time", says(x)[:120])
        x = await lead("Tomorrow around 5PM.")
        check("<Hangup" in x and re.search(r"5\s?pm", x, re.I) is not None and "when should" not in x.lower()
              and "day and time" not in x.lower(), "'Tomorrow around 5PM.' -> confirmed once, call ends", says(x)[:160])
    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
