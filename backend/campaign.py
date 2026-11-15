"""Campaign data, system-prompt rendering and the Vapi assistant definition.

Reads web/js/campaign.json — the same file the dashboard uses — so prompt, dashboard and
backend can never disagree.
"""
from __future__ import annotations

import json
from functools import lru_cache

from .settings import ROOT

CAMPAIGN_JSON = ROOT / "web" / "js" / "campaign.json"
PROMPT_TEMPLATE = ROOT / "prompts" / "system_prompt.template.md"


@lru_cache
def data() -> dict:
    return json.loads(CAMPAIGN_JSON.read_text(encoding="utf-8"))


def render_prompt() -> str:
    d = data()
    facts = 'Facts marked [web] come from public listings: for times and distances say "about" or "approximately".\n\n' + \
        "\n\n".join(
            f"## {g['group']}\n" + "\n".join(f"- {f['k']}: {f['v']}{' [web]' if f['src'] == 'web' else ''}" for f in g["items"])
            for g in d["facts"])
    pron = "\n".join(f"- {p['term']} → \"{p['say']}\"" for p in d["pronunciation"])
    return PROMPT_TEMPLATE.read_text(encoding="utf-8").replace("[[FACTS]]", facts).replace("[[PRONUNCIATION]]", pron)


def voice_config(voice_id: str | None = None) -> dict:
    d = data()
    return {
        **d["voiceSettings"],
        "voiceId": voice_id or d["pinnedVoices"][0]["id"],
        "chunkPlan": {"enabled": True, "formatPlan": {"enabled": True, "replacements": [
            {"type": "exact", "key": k, "value": v} for k, v in d["sayAs"]]}},
    }


# What the AI extracts from every call (Vapi "Structured Output").
LEAD_ANALYSIS_OUTPUT = {
    "name": "Lead Qualification",
    "type": "ai",
    "description": "Qualification result for a Divyasree Whispers of the Wind outbound call",
    "schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "2-3 sentence summary: who the lead is, what they said on each checkpoint, objections, and the agreed next step."},
            "interest": {"type": "string", "enum": ["hot", "warm", "cold"], "description": "hot = budget clearly fits (₹92.4 lakh+), location and timeline are OK, AND an expert callback is booked. warm = interested or callback booked, but budget is a stretch/unclear or another checkpoint is unresolved. cold = not interested, clearly not a fit, or asked not to be called."},
            "intent": {"type": "string", "description": "Self-use, Investment, Both, or Unknown, with a few words of detail."},
            "geography_fit": {"type": "string", "description": "Yes / No / Hesitant, plus a short reason."},
            "budget_fit": {"type": "string", "description": "Yes / No / Stretch, plus the budget mentioned if any."},
            "timeline_fit": {"type": "string", "description": "Yes / No / Unsure regarding December 2029 phased possession."},
            "sentiment_start": {"type": "string", "enum": ["positive", "calm", "hesitant", "irritated", "angry"]},
            "sentiment_end": {"type": "string", "enum": ["positive", "calm", "hesitant", "irritated", "angry"]},
            "language": {"type": "string", "enum": ["English", "Hindi", "Hinglish", "Other"]},
            "callback_time": {"type": "string", "description": "Agreed day/time for the Property Expert call, or empty if none."},
            "do_not_call": {"type": "boolean", "description": "True if the lead asked not to be contacted again."},
        },
        "required": ["summary", "interest", "sentiment_end", "do_not_call"],
    },
}


def build_assistant(*, system_prompt: str, voice_id: str | None, server_url: str | None, server_secret: str | None,
                    structured_output_id: str | None, llm: str = "openai:gpt-4.1-mini") -> dict:
    provider, _, model = llm.partition(":")
    a: dict = {
        "name": "Divya · Divyasree WOW",
        "firstMessageMode": "assistant-speaks-first",
        "firstMessage": "Hello {{ name | default: 'there' }}! This is Divya, a consultant from Divyasree Developers, "
                        "calling about Whispers of the Wind, our villa plot community near Nandi Hills in North Bengaluru. "
                        "Is this a good time for two minutes?",
        "model": {
            "provider": provider, "model": model, "temperature": 0.3,
            "maxTokens": 600 if provider == "groq" else 160,
            "messages": [{"role": "system", "content": system_prompt}],
            "tools": [{"type": "endCall"}],
        },
        "transcriber": {"provider": "deepgram", "model": "nova-3", "language": "multi"},
        "voice": voice_config(voice_id),
        "startSpeakingPlan": {"waitSeconds": 0.4, "smartEndpointingPlan": {"provider": "livekit"}},
        "stopSpeakingPlan": {"numWords": 1, "voiceSeconds": 0.2, "backoffSeconds": 1},
        "backgroundSpeechDenoisingPlan": {"smartDenoisingPlan": {"enabled": True}},
        "silenceTimeoutSeconds": 15,     # protects free credits
        "maxDurationSeconds": 240,       # hard cap: 4 minutes
        "endCallMessage": "Thank you for your time. Have a lovely day!",
        "voicemailMessage": "Hello, this is Divya from Divyasree Developers about Whispers of the Wind, our villa plots "
                            "near Nandi Hills. I will try you again later. Thank you!",
        "artifactPlan": {"recordingEnabled": True, "recordingFormat": "mp3",
                         **({"structuredOutputIds": [structured_output_id]} if structured_output_id else {})},
        "metadata": {"campaign_id": "divyasree-wow", "app": "vaani"},
    }
    if server_url:
        a["server"] = {"url": server_url, "timeoutSeconds": 20, **({"secret": server_secret} if server_secret else {})}
        a["serverMessages"] = ["end-of-call-report"]
    return a
