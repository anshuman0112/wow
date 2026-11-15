"""Create dummy lead files (CSV, Excel, JSON, SQL, TSV) in samples/ to test the Leads → Import feature.

Each file uses different, messy column names so you can see the importer map them to
name / phone / location / budget / email / notes. All people and numbers are made up.

    python scripts/make_sample_leads.py
"""
import csv
import json
from pathlib import Path

import openpyxl
from openpyxl.styles import Font

OUT = Path(__file__).resolve().parent.parent / "samples"
OUT.mkdir(exist_ok=True)

# 1) CSV with clean, standard headers + tricky phone formats, one duplicate, one invalid number
basic = [
    ["Name", "Phone", "City", "Budget", "Email", "Notes"],
    ["Rahul Sharma", "98450 10001", "Bengaluru", "1.2 Cr", "rahul.sharma@example.com", "Wants a weekend home"],
    ["Priya Nair", "+91-98450-10002", "Whitefield, Bengaluru", "95 Lakh", "priya.nair@example.com", "Investment, NRI parents"],
    ["Arjun Reddy", "09845010003", "Hyderabad", "80 Lakh", "arjun.r@example.com", "Budget may be low"],
    ["Sneha Iyer", "919845010004", "Chennai", "1.5 Cr", "sneha.iyer@example.com", "Asked about clubhouse"],
    ["Vikram Singh", "9845010005", "Delhi", "2 Cr", "vikram.s@example.com", "Prefers Hindi"],
    ["Ananya Gupta", "+971 50 100 0006", "Dubai", "1.8 Cr", "ananya.g@example.com", "NRI investor"],
    ["Rahul Sharma (duplicate)", "9845010001", "Bengaluru", "1.2 Cr", "", "Same phone as row 1 -> should be skipped"],
    ["Bad Number", "12345", "Pune", "90 Lakh", "", "Invalid phone -> should be rejected"],
]
with open(OUT / "1_leads_basic.csv", "w", newline="", encoding="utf-8") as f:
    csv.writer(f).writerows(basic)

# 2) Excel with "office style" headers + an extra column the importer should keep as extra
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Leads"
rows = [
    ["Customer Name", "Mob No.", "Locality", "Approx Budget", "Email ID", "Remarks", "Lead Source"],
    ["Karthik Menon", "98860 20001", "Hebbal, Bengaluru", "1.1 Cr", "karthik.m@example.com", "Works near airport", "Facebook Ad"],
    ["Meera Joshi", "98860 20002", "Yelahanka", "92 Lakh", "meera.j@example.com", "First-time buyer", "Google Ad"],
    ["Rohan Kapoor", "98860 20003", "Mumbai", "3 Cr", "rohan.k@example.com", "Looking at large plots", "Website"],
    ["Divya Rao", "98860 20004", "Devanahalli", "1 Cr", "divya.rao@example.com", "Lives 10 min away", "Referral"],
    ["Imran Khan", "98860 20005", "Mysuru", "75 Lakh", "imran.k@example.com", "Budget below entry price", "Facebook Ad"],
    ["Lakshmi Prasad", "98860 20006", "Bengaluru", "1.3 Cr", "lakshmi.p@example.com", "Wants possession date", "Walk-in"],
]
for r in rows:
    ws.append(r)
for c in ws[1]:
    c.font = Font(bold=True)
for col, width in zip("ABCDEFG", (18, 14, 20, 14, 26, 26, 14)):
    ws.column_dimensions[col].width = width
wb.save(OUT / "2_leads_office.xlsx")

# 3) JSON like a CRM export (different key names, nested-free)
crm = [
    {"full_name": "Suresh Babu", "mobile": "+91 98440 30001", "area": "Electronic City, Bengaluru",
     "price_range": "1.4 Cr", "mail": "suresh.b@example.com", "comments": "Wants site visit", "campaign": "Diwali 2026"},
    {"full_name": "Neha Verma", "mobile": "98440 30002", "area": "Noida", "price_range": "1 Cr",
     "mail": "neha.v@example.com", "comments": "Investment only", "campaign": "Diwali 2026"},
    {"full_name": "Aditya Kulkarni", "mobile": "98440-30003", "area": "Pune", "price_range": "2.2 Cr",
     "mail": "aditya.k@example.com", "comments": "Asked about RERA", "campaign": "Diwali 2026"},
    {"full_name": "Fatima Sheikh", "mobile": "9844030004", "area": "Bengaluru", "price_range": "85 Lakh",
     "mail": "fatima.s@example.com", "comments": "Location too far?", "campaign": "Diwali 2026"},
]
(OUT / "3_leads_crm_export.json").write_text(json.dumps(crm, indent=2), encoding="utf-8")

# 4) SQL dump (INSERT statements) from another system
sql = """-- Exported from an old CRM. Table and column names differ from ours on purpose.
INSERT INTO customers (cname, contact_no, region, investment, remarks) VALUES
  ('Gaurav Malhotra', '9900140001', 'Bengaluru', '1.6 Cr', 'Corporate executive'),
  ('Pooja Hegde', '9900140002', 'Mangaluru', '95 Lakh', 'Weekend home'),
  ('Sanjay Patil', '+91 99001 40003', 'Kolhapur', '70 Lakh', 'Budget concern');
INSERT INTO customers (cname, contact_no, region, investment, remarks) VALUES ('Anil Das', '9900140004', 'Kolkata', '1.2 Cr', 'Speaks Hindi');
"""
(OUT / "4_leads_crm_dump.sql").write_text(sql, encoding="utf-8")

# 5) TSV with Hindi-style / unusual headers (tests synonyms like "naam", "whatsapp", "place")
tsv = [
    ["Naam", "WhatsApp", "Place", "Range"],
    ["Ramesh Yadav", "98800 50001", "Bengaluru", "1 Cr"],
    ["Sunita Devi", "98800 50002", "Patna", "92 Lakh"],
    ["Harish Gowda", "98800 50003", "Doddaballapura", "1.1 Cr"],
]
with open(OUT / "5_leads_hindi_headers.tsv", "w", newline="", encoding="utf-8") as f:
    csv.writer(f, delimiter="\t").writerows(tsv)

# 6) CSV with odd headers the keyword rules don't know -> the AI column mapper has to work them out
odd = [
    ["Prospect", "Ph#", "Where they live", "Spend", "Any info"],
    ["Tarun Bhatia", "98451 60001", "Jayanagar, Bengaluru", "1.25 Cr", "Called twice before"],
    ["Kavya Shetty", "98451 60002", "Udupi", "1 Cr", "Interested in clubhouse"],
    ["Manoj Pillai", "98451 60003", "Kochi", "88 Lakh", "NRI, returning 2028"],
]
with open(OUT / "6_leads_odd_headers.csv", "w", newline="", encoding="utf-8") as f:
    csv.writer(f).writerows(odd)

print("Created:", ", ".join(sorted(p.name for p in OUT.iterdir() if p.suffix != ".md")))
