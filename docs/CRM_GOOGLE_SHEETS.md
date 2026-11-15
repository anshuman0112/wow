# Free CRM: Google Sheets (5 minutes, no new account)

After every call, the app automatically sends the lead's profile to a Google Sheet:
**one row per lead** (matched by phone), updated on every new call. Free, needs only your Google account.

| Updated | Name | Phone | City | Source | Score | Interest | … | Objections | Next action | Expert call | Calls |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 15 Nov 18:05 | Rahul | +9198… | Pune | Website form | 72 | warm | … | Budget ₹80 L below entry | Expert: Sun 5 pm, payment plan | Sunday 5 pm | 1 |

## Steps
1. Open **sheets.google.com** → **Blank spreadsheet**. Name it e.g. "WOW Leads CRM".
2. **Extensions → Apps Script**. Delete what is there and paste the whole file
   [`crm/google_sheets_crm.gs`](../crm/google_sheets_crm.gs).
3. On the line `const SECRET = 'CHANGE-ME';` replace `CHANGE-ME` with any random text, e.g. `wow-7f3k9q2x`. Save.
4. **Deploy → New deployment → Select type: Web app**.
   - Execute as: **Me**
   - Who has access: **Anyone**
   Press **Deploy**, allow the permissions Google asks for (it is your own script), and **copy the Web app URL**
   (it ends in `/exec`).
5. In the dashboard: **Settings → Sales team hand-off → CRM webhook**, paste:
   `YOUR_WEB_APP_URL?key=YOUR_SECRET` (e.g. `https://script.google.com/macros/s/AKfy…/exec?key=wow-7f3k9q2x`)
   and **Save settings** (admin PIN).
6. Done. After the next call, a row appears in the **Leads** tab of your sheet.
   The call's details on the Calls page show **CRM: sent (200)**.

## Notes
- "Anyone" access is needed so the app can reach the script; the `?key=` secret stops anyone else from writing to it.
- Google may answer with a redirect; the app treats it as delivered. If the CRM status shows "failed", check the URL and key.
- Want a "real" CRM later? HubSpot's free CRM can be connected the same way (ask for the HubSpot connector).
