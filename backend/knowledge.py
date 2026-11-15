"""Knowledge builder: any business document → clean fact sheet (to reuse WOW Voice Agent for another client)."""
from __future__ import annotations

from .clients import Groq, Supabase

SYSTEM = (
    "You turn a business document into a fact sheet for a phone sales agent. "
    "Copy facts exactly as written; never add, infer, round or guess anything. "
    "Group into sections such as Overview, Pricing, Location, Nearby, Amenities, Timeline, FAQs (skip empty ones). "
    'Reply with JSON only: {"sections":[{"title":"...","facts":["..."]}]}'
)


async def build_fact_sheet(groq: Groq, sb: Supabase, text: str, campaign_id: str) -> dict:
    out = await groq.json_chat(SYSTEM, text[:60000])
    sections = out.get("sections") or []
    facts_md = "\n\n".join(f"## {s['title']}\n" + "\n".join(f"- {f}" for f in s.get("facts", [])) for s in sections)
    await sb.update("campaigns", {"id": f"eq.{campaign_id}"}, {"facts_md": facts_md})
    return {"campaign_id": campaign_id, "facts_md": facts_md, "sections": sections}
