#!/usr/bin/env python
"""
Voyager ERP — Auto-loader for initial seed data & business records
Executes converted_inserts.sql if Ledgers table is empty.
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

try:
    import django
    django.setup()
    from django.db import connection
except Exception as e:
    print(f"[SKIP] Django setup skipped: {e}")
    sys.exit(0)


def load_data(force=False):
    print("=" * 60)
    print("  Checking TiDB Database Records")
    print("=" * 60)

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM `Ledgers`;")
            cnt = cursor.fetchone()[0]
            if cnt > 5 and not force:
                print(f"[OK] Database already has {cnt} ledgers. Data is ready!")
                return {"status": "already_loaded", "ledgers_count": cnt}
    except Exception as e:
        print(f"[INFO] Checking status: {e}")

    inserts_file = BASE_DIR / "converted_inserts.sql"
    if not inserts_file.exists():
        print(f"[WARNING] {inserts_file} not found.")
        return {"status": "error", "error": "converted_inserts.sql not found"}

    print("[INFO] Populating initial records from converted_inserts.sql...")
    with open(inserts_file, "r", encoding="utf-8") as f:
        sql_content = f.read()

    # Split statements
    statements = []
    for chunk in sql_content.split(";"):
        stmt = chunk.strip()
        if stmt and not stmt.startswith("--") and not stmt.upper().startswith("USE "):
            statements.append(stmt)

    print(f"[INFO] Found {len(statements)} statements to execute.")

    success = 0
    errors = 0
    with connection.cursor() as cursor:
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
        for stmt in statements:
            try:
                cursor.execute(stmt)
                success += 1
            except Exception as e:
                errors += 1
                if "Duplicate entry" not in str(e):
                    print(f"[WARN] Statement failed: {e}")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")

    try:
        connection.commit()
    except Exception:
        pass

    counts = {}
    with connection.cursor() as cursor:
        for tbl in ["Ledgers", "Ledger_Groups", "Tickets", "TicketLines", "JournalVoucher", "Vouchers", "CompanyMaster"]:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM `{tbl}`;")
                counts[tbl] = cursor.fetchone()[0]
            except Exception:
                pass

    print(f"[OK] Successfully executed {success} statements into database!")
    print(f"[OK] Row counts: {counts}")
    print("=" * 60)
    return {"status": "ok", "executed": success, "errors": errors, "counts": counts}


if __name__ == "__main__":
    force_run = "--force" in sys.argv
    load_data(force=force_run)

