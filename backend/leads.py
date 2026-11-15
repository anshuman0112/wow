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


CONTACTED = {"called", "calling", "queued"}


def duplicate_kind(existing: dict) -> str:
    """What to do when an imported phone number is already a lead (the number identifies the person).

    do_not_call       → never touch or call again
    re_engaged        → was called and NOT interested, now re-enquired → "Interested again", callable
    already_contacted → was called and interested / callback booked → skip, no repeat call
    already_listed    → in the list but not called yet → skip, no second copy
    """
    if existing.get("status") == "do_not_call":
        return "do_not_call"
    if existing.get("interest") == "cold" and existing.get("status") in CONTACTED | {"re_engaged"}:
        return "re_engaged"
    if existing.get("status") in CONTACTED or (existing.get("attempts") or 0) > 0 and existing.get("interest"):
        return "already_contacted"
    return "already_listed"


async def import_leads(sb: Supabase, rows: list[dict]) -> dict:
    """Add new leads; never create a second copy of a phone number. Report every duplicate by name."""
    from datetime import datetime, timezone
    leads = clean(rows)
    in_file_dupes = len(rows) - len(leads) - sum(1 for r in rows if not normalise_phone(r.get("phone")))
    existing: dict[str, dict] = {}
    phones = [l["phone"] for l in leads]
    for i in range(0, len(phones), 100):   # look up existing numbers in batches
        chunk = ",".join(f'"{p}"' for p in phones[i:i + 100])
        for e in await sb.select("leads", {"select": "id,name,phone,status,interest,attempts,notes",
                                           "phone": f"in.({chunk})"}):
            existing[e["phone"]] = e

    report: dict[str, list[dict]] = {"re_engaged": [], "already_contacted": [], "already_listed": [], "do_not_call": []}
    new = [l for l in leads if l["phone"] not in existing]
    now = datetime.now(timezone.utc)
    for l in leads:
        e = existing.get(l["phone"])
        if not e:
            continue
        kind = duplicate_kind(e)
        report[kind].append({"name": e.get("name") or l.get("name") or "Unknown", "status": e.get("status"),
                             "interest": e.get("interest")})
        if kind == "re_engaged":   # same person came back: flag them so the team calls again
            note = f"Re-enquired {now:%d %b %Y} via {l.get('source') or 'import'}"
            await sb.update("leads", {"id": f"eq.{e['id']}"}, {
                "status": "re_engaged", "re_engaged_at": now.isoformat(),
                "notes": f"{e['notes']} | {note}" if e.get("notes") else note})

    saved = await sb.upsert("leads", new, "phone", ignore_duplicates=True, returning=True) if new else []
    return {"received": len(rows), "imported": len(saved), "new": [s.get("name") or s["phone"][-4:] for s in saved],
            "duplicates_in_file": max(in_file_dupes, 0),
            "invalid": sum(1 for r in rows if not normalise_phone(r.get("phone"))), **report}
