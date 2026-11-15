"""Inbound line: a free Vapi phone number answered 24/7 by "Divya · Inbound".

    python scripts/setup_inbound.py

Creates (or updates) a second Vapi assistant — same brain, voice, analysis and webhook as the outbound one,
but it answers "Thank you for calling Divyasree Developers…" — and attaches a free Vapi US number to it.
IDs are saved to .env (VAPI_INBOUND_ASSISTANT_ID, VAPI_INBOUND_NUMBER_ID, VAPI_INBOUND_NUMBER).
Re-run any time: it updates in place. Inbound calls use Vapi credit (~$0.10/min).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import httpx  # noqa: E402

from backend.campaign import INBOUND_NOTE, render_prompt  # noqa: E402
from backend.settings import settings  # noqa: E402

FIRST = ("Hello! Thank you for calling Divyasree Developers, this is Divya. "
         "Are you calling about Whispers of the Wind, our villa plots near Nandi Hills?")
READ_ONLY = ("id", "orgId", "createdAt", "updatedAt", "isServerUrlSecretSet")


def save_env(key: str, value: str) -> None:
    env = ROOT / ".env"
    lines = [l for l in env.read_text(encoding="utf-8").splitlines() if not l.startswith(f"{key}=")]
    lines.append(f"{key}={value}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    s = settings()
    h = {"Authorization": f"Bearer {s.vapi_key}"}
    with httpx.Client(base_url="https://api.vapi.ai", headers=h, timeout=60) as v:
        base = v.get(f"/assistant/{s.vapi_assistant_id}").raise_for_status().json()
        a = {k: val for k, val in base.items() if k not in READ_ONLY}
        a["name"] = "Divya · Inbound"
        a["firstMessage"] = FIRST
        a["model"]["messages"] = [{"role": "system", "content": INBOUND_NOTE + render_prompt()}]
        a["metadata"] = {**(a.get("metadata") or {}), "direction": "inbound"}

        aid = os.environ.get("VAPI_INBOUND_ASSISTANT_ID", "")
        if aid:
            v.patch(f"/assistant/{aid}", json=a).raise_for_status()
            print(f"✓ Updated inbound assistant {aid}")
        else:
            aid = v.post("/assistant", json=a).raise_for_status().json()["id"]
            save_env("VAPI_INBOUND_ASSISTANT_ID", aid)
            print(f"✓ Created inbound assistant {aid}")

        nid = os.environ.get("VAPI_INBOUND_NUMBER_ID", "")
        if nid:
            n = v.patch(f"/phone-number/{nid}", json={"assistantId": aid}).raise_for_status().json()
        else:
            n, last = None, None
            for area in ("415", "650", "408", "510", "212", "646", "917", "312"):   # free Vapi numbers are US numbers
                r = v.post("/phone-number", json={"provider": "vapi", "numberDesiredAreaCode": area,
                                                  "assistantId": aid, "name": "Divya inbound (free)"})
                if r.is_success:
                    n = r.json()
                    break
                last = r
            if n is None:
                sys.exit(f"✗ Could not get a free Vapi number: {last.status_code if last else ''} {last.text[:300] if last else ''}")
            save_env("VAPI_INBOUND_NUMBER_ID", n["id"])
        number = n.get("number") or n.get("sipUri") or ""
        save_env("VAPI_INBOUND_NUMBER", number)
        print(f"✓ Inbound line: {number} → Divya · Inbound (status: {n.get('status')})")


if __name__ == "__main__":
    main()
