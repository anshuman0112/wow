"""Checks real phone calls against the assignment's conversation architecture (no AI used).

    python scripts/call_checklist.py            # last 8 phone calls
    python scripts/call_checklist.py 20

For each call: Introduction (Divyasree consultant + project + location + permission), the 4 checkpoints
(Intent, Geography, Budget, Timeline), the Pitch, the CTA (Property Expert call), affirmations, and
re-asking (a checkpoint asked again after the lead already answered it).
"""
from __future__ import annotations

import os
import re
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend.settings import settings  # noqa: E402

STEPS = {
    "Intro": lambda first: all(w in first.lower() for w in ("divyasree", "consultant", "whispers of the wind", "nandi"))
    and bool(re.search(r"good time|two minutes|is this a good", first.lower())),
    "Intent": r"weekend home or (as )?an investment|self[- ]use|investment\?|weekend home or",
    "Geography": r"nandi hills and devanahalli|devanahalli side|airport corridor\?",
    "Budget": r"ninety-two point four lakh|92\.4",
    "Timeline": r"december 2029",
    "Pitch": r"private valley|seventy-four percent|like-minded community",
    "CTA": r"what day and time|day and time would suit|which day|short call with (our|the) property expert",
}
AFFIRM = r"\b(understood|perfect|got it|great|wonderful|lovely|sure)\b"


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    s = settings()
    rows = httpx.get(f"{s.supabase_url}/rest/v1/calls", timeout=30,
                     headers={"apikey": s.supabase_key, "Authorization": f"Bearer {s.supabase_key}"},
                     params={"select": "vapi_call_id,started_at,messages,duration_sec,ended_reason",
                             "call_type": "eq.twilioPhoneCall", "order": "started_at.desc", "limit": str(n * 3)}).json()
    shown = 0
    for r in rows:
        msgs = r.get("messages") or []
        users = [m for m in msgs if m["role"] == "user"]
        if len(users) < 2:   # voicemail, no answer, or test stubs
            continue
        shown += 1
        divya = [m["text"] for m in msgs if m["role"] == "assistant"]
        said = " ".join(divya).lower()
        marks = {"Intro": STEPS["Intro"](divya[0] if divya else "")}
        for k, pat in list(STEPS.items())[1:]:
            marks[k] = bool(re.search(pat, said))
        affirm = len(re.findall(AFFIRM, said))
        # re-asking: the same checkpoint question spoken twice by Divya
        asks = [t for t in divya if t.rstrip().endswith("?")]
        repeats = [q[:50] for i, q in enumerate(asks) if q in asks[:i]]
        dur = r.get("duration_sec")
        print(f"\n{r['started_at'][:16]}  {len(users)} lead turns, {int(dur or 0)} s, ended: {r.get('ended_reason')}")
        print("   " + "  ".join(f"{'✅' if v else '❌'} {k}" for k, v in marks.items())
              + f"  | affirmations {affirm} | repeated questions {len(repeats)}")
        if repeats:
            print("   repeated:", repeats[:3])
        if shown >= n:
            break


if __name__ == "__main__":
    main()
