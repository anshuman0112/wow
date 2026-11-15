"""Render the system prompt and create/update Divya in Vapi (pointing her webhook at the Python API).

    python scripts/sync_assistant.py            # full sync
    python scripts/sync_assistant.py --dry-run  # only write docs/system_prompt.md
"""
from __future__ import annotations

import json
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252

import httpx  # noqa: E402

from backend.campaign import LEAD_ANALYSIS_OUTPUT, build_assistant, data, render_prompt  # noqa: E402
from backend.settings import settings  # noqa: E402

ENV = ROOT / ".env"
STATE = ROOT / "vapi" / ".state.json"
CONFIG_JS = ROOT / "web" / "js" / "config.js"
VAPI = "https://api.vapi.ai"


def set_env(key: str, value: str) -> None:
    text = ENV.read_text(encoding="utf-8")
    pattern = re.compile(rf"^{key}=.*$", re.M)
    text = pattern.sub(f"{key}={value}", text) if pattern.search(text) else text.rstrip("\n") + f"\n{key}={value}\n"
    ENV.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    prompt = render_prompt()
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "system_prompt.md").write_text(prompt, encoding="utf-8", newline="\n")
    print(f"✓ System prompt written to docs/system_prompt.md (~{len(prompt) // 4} tokens)")
    if "--dry-run" in sys.argv:
        return

    s = settings()
    if not s.vapi_key:
        sys.exit("✗ VAPI_PRIVATE_KEY missing in .env")
    secret = s.vapi_webhook_secret or secrets.token_urlsafe(32)
    if not s.vapi_webhook_secret:
        set_env("VAPI_WEBHOOK_SECRET", secret)
        print("✓ Generated VAPI_WEBHOOK_SECRET (also add it to Vercel env vars)")

    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    h = {"Authorization": f"Bearer {s.vapi_key}"}
    with httpx.Client(timeout=60) as c:
        def send(method: str, url: str, body: dict) -> dict:
            r = c.request(method, VAPI + url, json=body, headers=h)
            if r.is_error:
                sys.exit(f"✗ Vapi {method} {url} failed ({r.status_code}): {r.text}")
            return r.json() if r.content else {}

        if state.get("structuredOutputId"):
            send("PATCH", f"/structured-output/{state['structuredOutputId']}", LEAD_ANALYSIS_OUTPUT)
            print("✓ Updated structured output", state["structuredOutputId"])
        else:
            state["structuredOutputId"] = send("POST", "/structured-output", LEAD_ANALYSIS_OUTPUT)["id"]
            print("✓ Created structured output", state["structuredOutputId"])

        import os
        assistant = build_assistant(
            system_prompt=prompt,
            voice_id=os.environ.get("ELEVENLABS_VOICE_ID") or data()["pinnedVoices"][0]["id"],
            server_url=f"{s.public_base_url}/api/vapi/events", server_secret=secret,
            structured_output_id=state["structuredOutputId"],
            llm=os.environ.get("VAPI_LLM") or "openai:gpt-4.1-mini")
        print(f"  brain: {assistant['model']['provider']}/{assistant['model']['model']} · webhook: {assistant['server']['url']}")
        if state.get("assistantId"):
            send("PATCH", f"/assistant/{state['assistantId']}", assistant)
            print("✓ Updated assistant", state["assistantId"])
        else:
            state["assistantId"] = send("POST", "/assistant", assistant)["id"]
            print("✓ Created assistant", state["assistantId"])

    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))
    set_env("VAPI_ASSISTANT_ID", state["assistantId"])
    cfg = CONFIG_JS.read_text(encoding="utf-8")
    cfg = re.sub(r"vapiAssistantId: '[^']*'", f"vapiAssistantId: '{state['assistantId']}'", cfg)
    CONFIG_JS.write_text(cfg, encoding="utf-8", newline="\n")
    print("✓ .env and web/js/config.js updated")


if __name__ == "__main__":
    main()
