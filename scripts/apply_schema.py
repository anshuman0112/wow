"""Create/update the Supabase database from supabase/schema.sql.

    python scripts/apply_schema.py
Needs SUPABASE_URL and SUPABASE_DB_PASSWORD in .env.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252

import psycopg  # noqa: E402

from backend.settings import settings  # noqa: E402
import os  # noqa: E402

ref = re.search(r"https://([a-z0-9]+)\.supabase\.co", settings().supabase_url or "")
password = os.environ.get("SUPABASE_DB_PASSWORD", "")
if not ref or not password:
    sys.exit("✗ Need SUPABASE_URL and SUPABASE_DB_PASSWORD in .env")
ref = ref.group(1)

regions = ["ap-south-1", "ap-southeast-1", "us-east-1", "us-east-2", "us-west-1", "eu-central-1", "eu-west-1"]
targets = [(f"db.{ref}.supabase.co", "postgres")] + \
          [(f"{p}-{r}.pooler.supabase.com", f"postgres.{ref}") for r in regions for p in ("aws-0", "aws-1")]
sql = (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")

for host, user in targets:
    try:
        conn = psycopg.connect(host=host, port=5432, user=user, password=password, dbname="postgres",
                               sslmode="require", connect_timeout=6, autocommit=True)
    except psycopg.OperationalError as e:
        if "password authentication failed" in str(e):
            sys.exit("✗ Wrong database password (Supabase → Project Settings → Database).")
        continue
    with conn:
        conn.execute(sql)
        conn.execute("notify pgrst, 'reload schema'")
        rows = conn.execute("select table_name from information_schema.tables where table_schema='public' "
                            "and table_name in ('campaigns','leads','calls','leads_public','calls_public') order by 1").fetchall()
    print(f"✓ Schema applied via {host}: {', '.join(r[0] for r in rows)}")
    break
else:
    sys.exit("✗ Could not reach the database. Check the password or your network.")
