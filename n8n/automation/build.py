"""Builds the 4 n8n automation workflows (JSON files next to this script).

    python n8n/automation/build.py

n8n only needs the app's address and the shared key; everything else (who is due a call, scoring, calling
hours, duplicates) stays in the app. Workflows read settings from n8n's environment (the project .env):
  DIALER_SECRET        shared key (also the GitHub Actions secret DIALER_KEY)
  ALERT_EMAIL          where Hot-lead alerts and the 7 pm report go (e.g. the sales team's address)
  ALERT_FROM_EMAIL     the Gmail address that sends them (the one with the App password)
  LEADS_SHEET_CSV_URL  optional: a Google Sheet published as CSV (File > Share > Publish to web > CSV)
"""
from __future__ import annotations

import json
from pathlib import Path

APP = "https://vaani-divyasree.vercel.app"
HERE = Path(__file__).parent


def every_minute(name: str = "Every minute") -> dict:
    return {"parameters": {"rule": {"interval": [{"field": "minutes", "minutesInterval": 1}]}},
            "name": name, "type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.2, "position": [0, 0], "id": "trigger"}


def code(name: str, js: str, pos: list[int]) -> dict:
    return {"parameters": {"jsCode": js.strip()}, "name": name, "type": "n8n-nodes-base.code", "typeVersion": 2,
            "position": pos, "id": name.lower().replace(" ", "-")}


def email(name: str, subject: str, text: str, pos: list[int]) -> dict:
    return {"parameters": {"fromEmail": "={{ $env.ALERT_FROM_EMAIL }}", "toEmail": "={{ $env.ALERT_EMAIL }}",
                           "subject": subject, "emailFormat": "text", "text": text, "options": {}},
            "name": name, "type": "n8n-nodes-base.emailSend", "typeVersion": 2.1, "position": pos, "id": "email",
            "credentials": {"smtp": {"id": "wowGmailSmtp0001", "name": "Gmail SMTP"}}}


def workflow(wid: str, name: str, nodes: list[dict]) -> dict:
    conns = {nodes[i]["name"]: {"main": [[{"node": nodes[i + 1]["name"], "type": "main", "index": 0}]]}
             for i in range(len(nodes) - 1)}
    return {"id": wid, "name": name, "nodes": nodes, "connections": conns, "active": False,
            "settings": {"executionOrder": "v1", "timezone": "Asia/Kolkata", "saveDataSuccessExecution": "none"},
            "pinData": {}, "tags": []}


ASK_APP = """
// Small helper: call the WOW app with the shared key.
const call = (path, qs = {}) => this.helpers.httpRequest({
  method: 'GET', url: '%s/api' + path, qs, json: true, timeout: 90000,
  headers: { 'X-Dialer-Key': $env.DIALER_SECRET },
});
""" % APP

DIALER = ASK_APP + """
// Every minute: the app dials whoever is due (call-backs, re-attempts, new leads incl. CSV uploads),
// max a few per run, only 9 am - 9 pm IST. Safe to run as often as you like.
const res = await call('/dialer/tick');
return [{ json: { checked_at: res.checked_at || new Date().toISOString(), dialled: res.dialled || [], note: res.reason || '' } }];
"""

HOT = ASK_APP + """
// Every minute: fetch calls that finished since the last run; pass on only the Hot ones (one email each).
const memory = $getWorkflowStaticData('global');
const since = memory.since || new Date(Date.now() - 15 * 60 * 1000).toISOString();
const res = await call('/automation/events', { since });
const calls = res.calls || [];
if (calls.length) memory.since = calls[calls.length - 1].ended_at;   // next run starts after the newest one
if (!$env.ALERT_EMAIL) return [];                                   // no address yet: nothing to send
return (res.hot || []).map(c => ({ json: {
  name: c.name || 'Lead', score: c.score, phone: c.phone || '', intent: c.intent || '-',
  budget: c.budget_fit || '-', location: c.geography_fit || '-', timeline: c.timeline_fit || '-',
  expert_call: c.callback_time || 'not booked yet', next: c.next_action || '-', summary: c.summary || '', link: c.link,
}}));
"""

REPORT = ASK_APP + """
// 7 pm: today's numbers from the app, written as a short email.
const r = await call('/automation/report');
const booked = (r.expert_calls_booked || []).map(b => `  - ${b.name}: ${b.time}`).join('\\n') || '  (none)';
const backs = (r.call_backs_scheduled || []).map(b => `  - ${b.name}: ${b.at}`).join('\\n') || '  (none)';
const text = `WOW · Divya daily report · ${r.date}

Calls today: ${r.calls} (${r.minutes} minutes)
  Hot ${r.hot} · Warm ${r.warm} · Cold ${r.cold}
New leads today: ${r.new_leads}

Property Expert calls booked:
${booked}

Divya call-backs scheduled:
${backs}

Dashboard: %s/#/calls`;
if (!$env.ALERT_EMAIL) return [];
return [{ json: { subject: `Divya daily report · ${r.date}: ${r.calls} calls, ${r.hot} Hot`, text } }];
""" % APP

SHEET = """
// Every minute: new rows in a Google Sheet (published as CSV) become leads; the app then calls them.
// Sheet columns: name, phone, location, budget, notes (header row first). Rows already sent are remembered.
const url = $env.LEADS_SHEET_CSV_URL;
if (!url) return [];
const csv = await this.helpers.httpRequest({ method: 'GET', url, timeout: 30000 });
const lines = String(csv).split(/\\r?\\n/).filter(l => l.trim());
if (lines.length < 2) return [];
const split = l => (l.match(/("([^"]|"")*"|[^,]*)(,|$)/g) || []).map(c => c.replace(/,$/, '').replace(/^"|"$/g, '').replace(/""/g, '"').trim());
const head = split(lines[0]).map(h => h.toLowerCase());
const col = k => head.findIndex(h => h.includes(k));
const memory = $getWorkflowStaticData('global');
memory.sent = memory.sent || {};
const out = [];
for (const line of lines.slice(1)) {
  const c = split(line);
  const phone = (c[col('phone')] || c[col('mobile')] || '').trim();
  const key = phone.replace(/\\D/g, '').slice(-10);
  if (key.length < 10 || memory.sent[key]) continue;
  const res = await this.helpers.httpRequest({ method: 'POST', url: '%s/api/leads/inbound', json: true, timeout: 60000,
    body: { name: c[col('name')] || '', phone, location: c[col('location')] || c[col('city')] || '',
            budget: c[col('budget')] || '', notes: c[col('note')] || '', source: 'Google Sheet' } });
  memory.sent[key] = new Date().toISOString();
  out.push({ json: { phone, result: res.call || res.duplicate || 'saved' } });
}
return out;
""" % APP

FLOWS = {
    "wf_dialer.json": workflow("wowDialerEvery1m", "WOW 1 · Dialer (every minute)", [every_minute(), code("Ask app to dial due leads", DIALER, [260, 0])]),
    "wf_hot_alert.json": workflow("wowHotLeadAlert1", "WOW 2 · Hot-lead email alert", [
        every_minute(), code("Get new Hot calls", HOT, [260, 0]),
        email("Email sales", "=🔥 Hot lead: {{ $json.name }} ({{ $json.score }}/100)",
              "=Hot lead from Divya\n\nName: {{ $json.name }}\nPhone: {{ $json.phone }}\nScore: {{ $json.score }}/100\n"
              "Intent: {{ $json.intent }}\nLocation: {{ $json.location }}\nBudget: {{ $json.budget }}\nTimeline: {{ $json.timeline }}\n"
              "Property Expert call: {{ $json.expert_call }}\nNext step: {{ $json.next }}\n\nSummary: {{ $json.summary }}\n\n"
              "Open the call: {{ $json.link }}", [520, 0])]),
    "wf_daily_report.json": workflow("wowDailyReport7p", "WOW 3 · Daily report (7 pm)", [
        {"parameters": {"rule": {"interval": [{"field": "cronExpression", "expression": "0 19 * * *"}]}},
         "name": "Every day 7 pm", "type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.2, "position": [0, 0], "id": "trigger"},
        code("Build the report", REPORT, [260, 0]),
        email("Email the report", "={{ $json.subject }}", "={{ $json.text }}", [520, 0])]),
    "wf_sheet_leads.json": workflow("wowSheetToLeads1", "WOW 4 · Google Sheet to leads", [every_minute(), code("New sheet rows to leads", SHEET, [260, 0])]),
}

if __name__ == "__main__":
    for fname, wf in FLOWS.items():
        (HERE / fname).write_text(json.dumps(wf, indent=2, ensure_ascii=False), encoding="utf-8")
        print("wrote", fname)
