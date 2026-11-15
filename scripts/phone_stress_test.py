"""Stress test of live phone calls, WITHOUT ringing anyone.

Plays several complete calls against the server exactly as Twilio would send them (signed requests), fast,
with cut-off sentences, silences, duplicate deliveries, simultaneous requests and calls running in parallel.
After every step it checks the reply is valid TwiML, and at the end that each saved conversation is clean
(no double answers, nothing stuck half-heard, no lost turns).

    python scripts/phone_stress_test.py                       # live app
    python scripts/phone_stress_test.py http://127.0.0.1:8000  # local server
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import re
import statistics
import sys
import time
import uuid
from xml.dom import minidom

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import cache  # noqa: E402
from backend.settings import settings  # noqa: E402

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://vaani-divyasree.vercel.app").rstrip("/")
S = settings()
fails: list[str] = []
server_ms: list[int] = []
net_drops: list[str] = []

# Each step: ("say", text) = Twilio's final speech result · ("silence",) = Gather timed out
# ("dup", text) = same result delivered twice (network retry) · ("race", text) = two copies at the same moment
CALLS = {
    "fast_full_call": [("say", "Yes."), ("say", "Investment."), ("say", "Yes, comfortable."), ("say", "Yes, that works."),
                       ("say", "Yes, fine."), ("say", "Just me."), ("say", "Saturday at 11 am.")],
    "cutoffs_and_pauses": [("say", "Yes. I'm"), ("say", "looking at it as a weekend home."), ("say", "Me about all"),
                           ("say", "the amenities?"), ("say", "Before going, can you please tell me when you"),
                           ("silence",), ("say", "The EMI plan and the loan"), ("silence",), ("say", "Yes, that range works."),
                           ("say", "Can you tell me about the"), ("say", "schools nearby?")],
    "network_retries_and_races": [("say", "Yes."), ("dup", "It is for investment."), ("race", "Yes, I am comfortable."),
                                  ("say", "What is the price?"), ("dup", "Okay, that works."), ("say", "December 2029 is fine.")],
    "hinglish": [("say", "Haan ji."), ("say", "Investment ke liye dekh raha hoon."), ("say", "Haan, theek hai."),
                 ("say", "Price kitna hai?"), ("say", "Chalega.")],
    "busy_callback": [("say", "I'm busy right now."), ("say", "Call me tomorrow at 5 pm.")],
    "irritated_not_interested": [("say", "Who gave you my number?"), ("say", "I am not interested. Don't call me again.")],
    "silent_lead": [("silence",), ("silence",)],
    "long_call": [("say", "Yes.")] + [("say", q) for q in [
        "What is this project about?", "Where exactly is it?", "How far is the airport?", "What are the amenities?",
        "Is there a clubhouse?", "Any schools nearby?", "Hospitals?", "What is the price?", "What about EMI and loans?",
        "When is possession?", "Is it RERA registered?", "What plot sizes are there?", "How many plots?",
        "Is it gated?", "Who is it for?"]],
}


def sign(url: str, data: dict) -> str:
    raw = url + "".join(k + data[k] for k in sorted(data))
    return base64.b64encode(hmac.new(S.twilio_token.encode(), raw.encode(), hashlib.sha1).digest()).decode()


def says(xml: str) -> str:
    return " | ".join(re.findall(r"<Say[^>]*>(.*?)</Say>", xml))


async def run_call(c: httpx.AsyncClient, name: str, steps: list) -> None:
    sid = "CA" + uuid.uuid4().hex
    ended = False

    async def post(path: str, data: dict) -> tuple[int, str]:
        url = BASE + path
        data = {"CallSid": sid, "AccountSid": S.twilio_sid, "CallStatus": "in-progress", **data}
        for attempt in range(2):   # my laptop's connection can drop; retry once and COUNT it (reported at the end)
            try:
                r = await c.post(url, data=data, headers={"X-Twilio-Signature": sign(url, data)})
                break
            except httpx.TransportError as e:
                net_drops.append(f"{name}: {type(e).__name__} on {path}")
                if attempt:
                    fails.append(f"{name}: no response twice on {path} ({type(e).__name__})")
                    return 0, ""
        m = re.search(r"dur=(\d+)", r.headers.get("server-timing", ""))
        if m:
            server_ms.append(int(m.group(1)))
        return r.status_code, r.text

    def ok_xml(label: str, st: int, x: str) -> bool:
        try:
            minidom.parseString(x.encode())
            good = st == 200
        except Exception:  # noqa: BLE001
            good = False
        if not good:
            fails.append(f"{name}: {label} -> HTTP {st} / invalid TwiML: {x[:120]}")
        return good

    st, x = await post("/api/phone/start?lead=&stt=nova3", {"To": "+910000000000"})
    ok_xml("start", st, x)
    for step in steps:
        if ended:
            break
        kind = step[0]
        if kind == "silence":
            st, x = await post("/api/phone/turn?lead=&silence=1", {})
            ok_xml("silence", st, x)
        elif kind == "say":
            st, x = await post("/api/phone/turn?lead=", {"SpeechResult": step[1], "Confidence": "0.9"})
            ok_xml(step[1], st, x)
        elif kind == "dup":   # Twilio retried the same webhook: the same reply must come back, answered once
            s1, x1 = await post("/api/phone/turn?lead=", {"SpeechResult": step[1]})
            s2, x2 = await post("/api/phone/turn?lead=", {"SpeechResult": step[1]})
            ok_xml(step[1], s1, x1)
            ok_xml(step[1] + " (retry)", s2, x2)
            x = x2
        elif kind == "race":
            (s1, x1), (s2, x2) = await asyncio.gather(post("/api/phone/turn?lead=", {"SpeechResult": step[1]}),
                                                      post("/api/phone/turn?lead=", {"SpeechResult": step[1]}))
            ok_xml(step[1] + " (A)", s1, x1)
            ok_xml(step[1] + " (B)", s2, x2)
            x = x2
        ended = "<Hangup" in x
    async with httpx.AsyncClient(timeout=30) as h:
        row = await cache.get_session(h, sid) or {}
    msgs = row.get("messages") or []
    raw = row.get("raw") or {}
    doubles = [i for i in range(1, len(msgs)) if msgs[i]["role"] == msgs[i - 1]["role"]
               and "try you another time" not in msgs[i]["text"]]   # greeting then goodbye to a silent lead is correct
    if doubles:
        fails.append(f"{name}: two lines in a row from the same side at {doubles} -> {[msgs[i]['text'][:40] for i in doubles]}")
    if raw.get("pending"):
        fails.append(f"{name}: left waiting on a half sentence: {raw['pending']!r}")
    user_turns = sum(1 for m in msgs if m["role"] == "user")
    sent = sum(1 for s in steps if s[0] in ("say", "dup", "race"))
    if name.startswith("network_retries") and user_turns != sent:
        fails.append(f"{name}: {sent} things said but {user_turns} lead turns saved (copies answered twice?)")
    last = next((m["text"] for m in reversed(msgs) if m["role"] == "assistant"), "")
    print(f"  {name:28} {user_turns:2} lead turns, {len(msgs):2} lines, ended={'yes' if ended else 'no '} | last: {last[:70]}")


async def main() -> None:
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=40) as c:
        print("Round 1: every call on its own, as fast as possible")
        for name, steps in CALLS.items():
            await run_call(c, name, steps)
        print("\nRound 2: three calls at the same time")
        await asyncio.gather(*(run_call(c, f"{n} (parallel)", CALLS[n]) for n in ("fast_full_call", "cutoffs_and_pauses", "hinglish")))
    total = time.perf_counter() - t0
    print(f"\nServer time per step: median {statistics.median(server_ms):.0f} ms, p95 "
          f"{sorted(server_ms)[int(len(server_ms) * 0.95) - 1]:.0f} ms, max {max(server_ms)} ms ({len(server_ms)} steps, {total:.0f} s total)")
    if net_drops:
        print(f"\nConnection drops between this laptop and the server (retried): {len(net_drops)}")
        for d in net_drops:
            print("  ", d)
    if fails:
        print(f"\n{len(fails)} PROBLEM(S):")
        for f in fails:
            print("  FAIL", f)
        sys.exit(1)
    print("\nALL CLEAN: valid replies, no double answers, nothing stuck, nothing lost")


if __name__ == "__main__":
    asyncio.run(main())
