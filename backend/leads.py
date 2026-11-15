"""Lead import: AI column mapping (Groq) and server-side cleaning before saving to Supabase."""
from __future__ import annotations

import re

from .clients import Groq, Supabase
from .settings import settings

FIELDS = ["name", "phone", "email", "location", "budget", "notes", "extra"]

MAPPING_SYSTEM = (
    "You map spreadsheet columns to a CRM lead schema. Fields: name, phone, email, location, budget, notes. "
    'Use "extra" for anything else. Each field may be used at most once, except "extra". '
    'Reply with JSON only: {"mapping": {"<column>": "<field>"}}.'
)


def normalise_phone(raw: object) -> str | None:
    p = re.sub(r"[^\d+]", "", str(raw or ""))
    if p.startswith("00"):
        p = "+" + p[2:]
    if not p.startswith("+"):
        if len(p) == 10:
            p = "+91" + p
        elif len(p) == 12 and p.startswith("91"):
            p = "+" + p
        elif len(p) == 11 and p.startswith("0"):
            p = "+91" + p[1:]
    return p if re.fullmatch(r"\+\d{10,15}", p) else None


async def ai_mapping(groq: Groq, headers: list[str], sample: list[dict]) -> dict[str, str] | None:
    try:
        out = await groq.json_chat(MAPPING_SYSTEM, f"Columns: {headers}\nSample rows: {sample[:5]}")
        raw = out.get("mapping") or {}
        return {h: (raw.get(h) if raw.get(h) in FIELDS else "extra") for h in headers}
    except Exception:  # noqa: BLE001 — the browser falls back to keyword matching
        return None


def clean(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for r in rows:
        phone = normalise_phone(r.get("phone"))
        if not phone or phone in seen:
            continue
        seen.add(phone)
        s = lambda k: (str(r[k]).strip()[:500] if r.get(k) not in (None, "") else None)  # noqa: E731
        out.append({
            "phone": phone, "name": (s("name") or "")[:120] or None, "email": s("email"),
            "location": s("location"), "budget": s("budget"), "notes": s("notes"),
            "source": s("source") or "upload",
            "extra": r["extra"] if isinstance(r.get("extra"), dict) else {},
            "campaign_id": settings().campaign_id,
        })
    return out


async def import_leads(sb: Supabase, rows: list[dict]) -> dict:
    leads = clean(rows)
    saved = await sb.upsert("leads", leads, "phone", ignore_duplicates=True, returning=True) if leads else []
    return {"received": len(rows), "imported": len(saved), "skipped": len(rows) - len(saved)}
