"""Sign-in for the dashboard.

  • One admin account: ADMIN_EMAIL + ADMIN_PASSWORD_HASH (PBKDF2-SHA256, 310k rounds; the password itself is never stored).
  • Login returns a signed session token (HMAC with SESSION_SECRET), valid 7 days. The browser sends it as
    "Authorization: Bearer <token>" on every API call.
  • Every /api route needs a valid session EXCEPT the public ones lead sources, phone carriers and the
    scheduler must reach (see PUBLIC below). Wrong passwords are rate-limited per visitor.

Create the hash:  python -c "from backend.auth import hash_password; print(hash_password('your password'))"
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time

SESSION_DAYS = 7
ROUNDS = 310_000

# Routes that must work without signing in (called by websites, ad platforms, Twilio, Vapi, the scheduler).
PUBLIC = [
    r"^/api/health$", r"^/api/config$", r"^/api/auth/login$",
    r"^/api/leads/inbound$", r"^/api/leads/meta$", r"^/api/leads/google$",        # lead sources
    r"^/api/phone/(start|turn|status|stream-start|relay-start|partial|next|recording)$", r"^/api/twiml(/.*)?$",     # Twilio (signature-checked)
    r"^/api/vapi/events$",                                                     # Vapi (secret-checked)
    r"^/api/dialer/tick$", r"^/api/automation/(events|report)$",   # n8n / GitHub scheduler (secret-key checked)                                                     # scheduler (dials only due leads)
    r"^/api/handoff/echo$",                                                    # CRM test receiver (write-only)
]
_PUBLIC_RE = [re.compile(p) for p in PUBLIC]


def is_public(path: str) -> bool:
    return any(p.match(path) for p in _PUBLIC_RE)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ROUNDS)
    return f"pbkdf2_sha256${ROUNDS}${_b64(salt)}${_b64(dk)}"


def check_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt, dk = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), _unb64(salt), int(rounds))
        return hmac.compare_digest(got, _unb64(dk))
    except (ValueError, TypeError):
        return False


def configured() -> bool:
    return bool(os.environ.get("ADMIN_EMAIL") and os.environ.get("ADMIN_PASSWORD_HASH") and os.environ.get("SESSION_SECRET"))


def _sign(body: str) -> str:
    return _b64(hmac.new(os.environ["SESSION_SECRET"].encode(), body.encode(), hashlib.sha256).digest())


def login(email: str, password: str) -> dict | None:
    if not configured():
        return None
    ok_email = hmac.compare_digest(email.strip().lower(), os.environ["ADMIN_EMAIL"].strip().lower())
    ok_pass = check_password(password, os.environ["ADMIN_PASSWORD_HASH"])   # always run (same timing either way)
    if not (ok_email and ok_pass):
        return None
    exp = int(time.time()) + SESSION_DAYS * 86400
    body = _b64(json.dumps({"sub": os.environ["ADMIN_EMAIL"].strip().lower(), "exp": exp}).encode())
    return {"token": f"{body}.{_sign(body)}", "email": os.environ["ADMIN_EMAIL"].strip().lower(), "expires": exp}


def verify(token: str) -> str | None:
    """Session token → email, or None if missing, tampered or expired."""
    if not (token and configured() and "." in token):
        return None
    body, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(body)):
        return None
    try:
        data = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    return data.get("sub") if data.get("exp", 0) > time.time() else None


def bearer(headers) -> str:
    h = headers.get("authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else ""
