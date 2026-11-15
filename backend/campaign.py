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


INBOUND_NOTE = """# INBOUND CALL (the lead called you)
Your first line already greeted them and asked if they are calling about Whispers of the Wind. Do NOT ask for
permission to speak. If you do not know their name, ask it once, naturally. Answer their question first, then
follow the same flow below: the 4 checkpoints, the soft "who decides" question, the pitch, and the Property Expert call.

"""


def render_prompt() -> str:
    d = data()
    facts = 'Facts marked [web] come from public listings: for times and distances say "about" or "approximately".\n\n' + \
        "\n\n".join(
            f"## {g['group']}\n" + "\n".join(f"- {f['k']}: {f['v']}{' [web]' if f['src'] == 'web' else ''}" for f in g["items"])
            for g in d["facts"])
    pron = "\n".join(f"- {p['term']} → \"{p['say']}\"" for p in d["pronunciation"])
    text = PROMPT_TEMPLATE.read_text(encoding="utf-8").replace("[[FACTS]]", facts).replace("[[PRONUNCIATION]]", pron)
    from . import config_store   # Divya's questions as set on the Settings page
    for k, q in config_store.questions().items():
        text = text.replace(f"[[Q_{k.upper()}]]", q["en"])
    return text


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
            "geography_fit": {"type": "string", "description": "Start with exactly one of: Yes / Hesitant / No / Not discussed. Then a short reason."},
            "budget_fit": {"type": "string", "description": "Start with exactly one of: Yes / Stretch / No / Not discussed. Then the budget mentioned if any."},
            "timeline_fit": {"type": "string", "description": "About December 2029 phased possession. Start with exactly one of: Yes / Unsure / No / Not discussed. Use Not discussed if the lead never answered it."},
            "sentiment_start": {"type": "string", "enum": ["positive", "calm", "hesitant", "irritated", "angry"]},
            "sentiment_end": {"type": "string", "enum": ["positive", "calm", "hesitant", "irritated", "angry"]},
            "language": {"type": "string", "enum": ["English", "Hindi", "Hinglish", "Other"]},
            "callback_time": {"type": "string", "description": "Agreed day/time for the Property Expert call, or empty if none."},
            "do_not_call": {"type": "boolean", "description": "True if the lead asked not to be contacted again."},
            "decision_maker": {"type": "string", "enum": ["self", "spouse", "family", "someone_else", "unknown"],
                               "description": "Who makes the buying decision, ONLY from what the lead actually said: self (they said they decide alone), spouse (with husband/wife/partner), family (with parents/family), someone_else (another person decides), unknown (not discussed - never guess)."},
            "objections": {"type": "array", "items": {"type": "string"},
                           "description": "JSON array of strings: every concern or objection the lead raised, each short (e.g. 'Budget ₹80 L is below the ₹92.4 L entry', 'Feels far from the city', 'Busy right now'). A budget below ₹92.4 lakh is always an objection. Empty array if none."},
            "next_action": {"type": "string", "description": "One concrete recommended next step for the sales team, e.g. 'Property Expert to call Sun 5 pm and show the staged payment plan for a ~₹80 L budget'."},
            "evidence": {"type": "object", "description": "JSON object with exactly these keys: intent, geography, budget, timeline, decision. Each value is a short exact quote of the LEAD's own words about that checkpoint (e.g. budget: 'my budget is around 80 lakh'), or an empty string if they said nothing about it.",
                         "properties": {"intent": {"type": "string"}, "geography": {"type": "string"}, "budget": {"type": "string"},
                                        "timeline": {"type": "string"}, "decision": {"type": "string"}}},
            "lead_busy": {"type": "boolean", "description": "True if the lead said they were busy / it was not a good time to talk and wanted to be called later."},
            "call_back_request": {"type": "string", "description": "If the lead asked Divya to call them back later, exactly when they said, in their words (e.g. 'tomorrow 5 pm', 'after 2 hours', 'kal shaam 6 baje', 'Monday morning'). Empty if they did not. This is NOT the Property Expert call."},
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
