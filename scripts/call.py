"""Ring a real phone and connect it to Divya, from the terminal.

    python scripts/call.py +916360246901          # call a number directly (Twilio bridge)
    python scripts/call.py --lead <lead uuid>      # call a saved lead (same as the dashboard's "Call now")
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252

import httpx  # noqa: E402

from backend import phone  # noqa: E402
from backend.clients import Twilio  # noqa: E402
from backend.leads import normalise_phone  # noqa: E402
from backend.settings import settings  # noqa: E402


async def main(args: list[str]) -> None:
    s = settings()
    async with httpx.AsyncClient(timeout=30) as http:
        if args[:1] == ["--lead"] and len(args) > 1:
            res = await phone.call_lead(http, args[1])
        else:
            number = normalise_phone(args[0] if args else "")
            if not number:
                sys.exit(__doc__)
            if s.phone_line != "twilio-bridge":
                sys.exit("✗ Needs TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER and VAPI_SIP_URI in .env")
            r = await Twilio(http).call(number, s.twilio_number, f"{s.public_base_url}/api/twiml")
            res = {"ok": True, "via": "twilio-bridge", "id": r.get("sid")}
    print(f"✓ Ringing now ({res['via']}, {res['id']}). Answer, press any key after Twilio's trial message, and Divya will speak.")


if __name__ == "__main__":
    try:
        asyncio.run(main(sys.argv[1:]))
    except Exception as e:  # noqa: BLE001
        sys.exit(f"✗ {e}")
