# Sample lead files (dummy data)

Use these to test **Leads → Import** on the dashboard. All names, emails and phone numbers are made up.
Each file uses different column names on purpose, so you can see the importer work out which column is which.
Re-create them any time with `python scripts/make_sample_leads.py`.

| File | Format | Column names used | What you should see |
|---|---|---|---|
| `1_leads_basic.csv` | CSV | Name, Phone, City, Budget, Email, Notes | 8 rows → **6 imported**, 1 bad number rejected (`12345`), 1 duplicate skipped. Phone formats like `09845010003`, `+91-98450-10002` and a Dubai number all come out clean. |
| `2_leads_office.xlsx` | Excel | Customer Name, Mob No., Locality, Approx Budget, Email ID, Remarks, Lead Source | **6 imported**. "Lead Source" is kept as an extra field. |
| `3_leads_crm_export.json` | JSON | full_name, mobile, area, price_range, mail, comments, campaign | **4 imported**. "campaign" is kept as an extra field. |
| `4_leads_crm_dump.sql` | SQL INSERTs | cname, contact_no, region, investment, remarks | **4 imported** from two INSERT statements. |
| `5_leads_hindi_headers.tsv` | TSV | Naam, WhatsApp, Place, Range | **3 imported**. Hindi / informal headers are understood. |
| `6_leads_odd_headers.csv` | CSV | Prospect, Ph#, Where they live, Spend, Any info | **3 imported**. Headers no keyword rule knows; the AI column mapper works them out. |

**How columns are matched:** the AI mapper (Groq, free) reads the headers and a few sample rows. If it is unavailable,
keyword rules take over (e.g. "Mob No." → phone, "Locality" → location). You can always correct a column in the
preview before pressing **Import**.

**Calls:** importing never calls anyone. On the free Twilio trial only verified numbers can be called, so these dummy
numbers cannot ring anybody.
