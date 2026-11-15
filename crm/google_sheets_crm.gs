/**
 * Free CRM in Google Sheets for the WOW voice agent.
 *
 * After every call, the app sends the lead profile here (Settings → Sales team hand-off → CRM webhook).
 * One row per lead (matched by phone): a new lead adds a row, a repeat call updates that row.
 *
 * Setup (5 minutes): see docs/CRM_GOOGLE_SHEETS.md
 */
const SECRET = 'CHANGE-ME';   // any random text; add the same as ?key=... at the end of the webhook URL in Settings

const COLUMNS = ['Updated', 'Name', 'Phone', 'City', 'Source', 'Score', 'Interest', 'Intent', 'Location fit',
  'Budget fit', 'Timeline fit', 'Decision maker', 'Objections', 'Next action', 'Expert call', 'Call-back at',
  'Summary', 'Calls', 'Last call ID'];

function doPost(e) {
  if ((e.parameter.key || '') !== SECRET) return reply({ ok: false, error: 'bad key' });
  const body = JSON.parse(e.postData.contents || '{}');
  const p = body.lead || {};
  if (!p.phone) return reply({ ok: false, error: 'no phone' });

  const sheet = getSheet();
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);   // two calls finishing at once never write the same row twice
  try {
    const phones = sheet.getRange(2, 3, Math.max(sheet.getLastRow() - 1, 1), 1).getValues().map(r => String(r[0]));
    const at = phones.indexOf(String(p.phone));
    const prevCalls = at >= 0 ? Number(sheet.getRange(at + 2, 18).getValue() || 0) : 0;
    const row = [new Date(), p.name || '', p.phone, p.city || '', p.source || '', p.score ?? '', p.interest || '',
      p.intent || '', p.location_fit || '', p.budget_fit || '', p.timeline_fit || '', p.decision_maker || '',
      (p.objections || []).join('; '), p.next_action || '', p.expert_call || '', p.call_back_at || '',
      p.summary || '', prevCalls + 1, p.call_id || ''];
    if (at >= 0) sheet.getRange(at + 2, 1, 1, row.length).setValues([row]);
    else sheet.appendRow(row);
  } finally {
    lock.releaseLock();
  }
  return reply({ ok: true });
}

function getSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName('Leads') || ss.insertSheet('Leads');
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(COLUMNS);
    sheet.setFrozenRows(1);
    sheet.getRange(1, 1, 1, COLUMNS.length).setFontWeight('bold');
  }
  return sheet;
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
