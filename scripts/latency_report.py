"""Phone-call latency report from REAL calls (nothing estimated).

    python scripts/latency_report.py            # last 20 phone calls
    python scripts/latency_report.py 50         # last 50

For every turn the server stores (calls.raw.usage[]):
  t_ms.load    reading the call's session (Redis)
  t_ms.reply   deciding the reply (FAQ cache, rules or the AI, incl. any model switches)
  attempts     each Groq request: model, HTTP status (429 = free limit hit), milliseconds
  seconds      Groq's own compute time; queue_s = time waiting in Groq's queue

Not measurable by us (happens inside Twilio): how long Twilio waits after you stop talking, and how
long its voice takes to start. Those are on top of these numbers.
"""
from __future__ import annotations

import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ["SUPABASE_SERVICE_KEY"]
    rows = httpx.get(f"{url}/rest/v1/calls", headers={"apikey": key, "Authorization": f"Bearer {key}"},
                     params={"select": "started_at,raw", "call_type": "eq.twilioPhoneCall",
                             "order": "started_at.desc", "limit": str(n)}, timeout=30).json()
    turns = [u for r in rows for u in ((r.get("raw") or {}).get("usage") or []) if u]
    timed = [u for u in turns if u.get("t_ms")]
    print(f"{len(rows)} calls, {len(turns)} turns ({len(timed)} with server timings)\n")

    def line(label: str, xs: list[float], unit: str = "ms") -> None:
        if xs:
            print(f"  {label:34} n={len(xs):3}  p50 {pct(xs, 50):6.0f}{unit}  p95 {pct(xs, 95):6.0f}{unit}  max {max(xs):6.0f}{unit}")

    print("Our server, per turn:")
    line("decide reply (all turns)", [u["t_ms"]["reply"] for u in timed])
    line("decide reply (AI turns)", [u["t_ms"]["reply"] for u in timed if "/" in str(u.get("model"))])
    line("decide reply (FAQ/rule turns)", [u["t_ms"]["reply"] for u in timed if "/" not in str(u.get("model"))])
    line("load session", [u["t_ms"]["load"] for u in timed])
    print("\nGroq:")
    line("compute (Groq-side)", [u["seconds"] * 1000 for u in turns if u.get("seconds")])
    line("queue (Groq-side)", [u["queue_s"] * 1000 for u in turns if u.get("queue_s") is not None])
    attempts = [a for u in timed for a in (u.get("attempts") or [])]
    hits = sum(1 for a in attempts if a.get("status") == 429)
    print(f"  requests {len(attempts)}, rate-limited (429) {hits}, "
          f"turns that needed a 2nd model {sum(1 for u in timed if len(u.get('attempts') or []) > 1)}")
    models: dict[str, int] = {}
    for u in turns:
        models[str(u.get("model"))] = models.get(str(u.get("model")), 0) + 1
    print("\nWho answered:", ", ".join(f"{m} {c}" for m, c in sorted(models.items(), key=lambda x: -x[1])))
    print("(rule:fallback / timeout = the AI was too slow or busy and a scripted line was used)")


if __name__ == "__main__":
    main()
