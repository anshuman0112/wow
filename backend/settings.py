"""Configuration from environment variables.

On Vercel they come from Project → Settings → Environment Variables.
Locally they are read from the project's .env file (never committed).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if value and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


class Settings:
    def __init__(self) -> None:
        g = lambda k, d="": os.environ.get(k, d).strip()  # noqa: E731
        self.supabase_url = g("SUPABASE_URL").rstrip("/")
        self.supabase_key = g("SUPABASE_SERVICE_ROLE_KEY")
        self.vapi_key = g("VAPI_PRIVATE_KEY")
        self.vapi_assistant_id = g("VAPI_ASSISTANT_ID")
        self.vapi_phone_number_id = g("VAPI_PHONE_NUMBER_ID")   # paid number imported into Vapi (optional)
        self.vapi_sip_uri = g("VAPI_SIP_URI")                   # free SIP line for the Twilio bridge
        self.vapi_webhook_secret = g("VAPI_WEBHOOK_SECRET")     # Vapi sends it as X-Vapi-Secret
        self.groq_key = g("GROQ_API_KEY")
        self.groq_model = g("GROQ_MODEL", "openai/gpt-oss-120b")
        self.twilio_sid = g("TWILIO_ACCOUNT_SID")
        self.twilio_token = g("TWILIO_AUTH_TOKEN")
        self.twilio_number = g("TWILIO_PHONE_NUMBER")
        self.public_base_url = g("PUBLIC_BASE_URL", "https://vaani-divyasree.vercel.app").rstrip("/")
        self.telegram_token = g("TELEGRAM_BOT_TOKEN")
        self.telegram_chat = g("TELEGRAM_CHAT_ID")
        self.campaign_id = g("CAMPAIGN_ID", "divyasree-wow")

        # How Twilio calls are handled: "gather" (free trial: Twilio speech + our Python loop)
        # or "sip" (paid accounts: bridge the call into Vapi's SIP line for the full Vapi experience).
        self.twilio_mode = g("TWILIO_MODE", "gather")
        self.twilio_check_signature = g("TWILIO_CHECK_SIGNATURE", "1") != "0"

        # Live streaming engine (Twilio Media Streams ⇄ WebSocket). Needs an always-on server
        # (Vercel functions can't hold a WebSocket), e.g. `uvicorn backend.main:app` + a tunnel, or Render.
        self.stream_base_url = g("STREAM_BASE_URL").rstrip("/")         # https://<always-on host>
        self.elevenlabs_key = g("ELEVENLABS_API_KEY")
        # Free ElevenLabs plans can only use built-in voices over the API: "Sarah" (clear, multilingual).
        self.stream_voice_id = g("STREAM_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")
        self.stream_end_silence_ms = int(g("STREAM_END_SILENCE_MS", "600"))   # pause that ends the lead's turn

    @property
    def phone_line(self) -> str:
        """Which way real phone calls go out."""
        if self.vapi_phone_number_id:
            return "vapi-number"
        if self.twilio_sid and self.twilio_token and self.twilio_number:
            if self.twilio_mode == "sip" and self.vapi_sip_uri:
                return "twilio-sip"
            if self.twilio_mode == "stream" and self.stream_base_url and self.elevenlabs_key:
                return "twilio-stream"
            return "twilio-gather"
        return "none"


@lru_cache
def settings() -> Settings:
    return Settings()
