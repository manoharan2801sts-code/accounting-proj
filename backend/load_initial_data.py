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
            ssr_cnt = 0
            try:
                cursor.execute("SELECT COUNT(*) FROM `SSR_AL_Tickets`;")
                ssr_cnt = cursor.fetchone()[0]
            except Exception:
                ssr_cnt = 0

            if cnt > 5 and ssr_cnt > 0 and not force:
                print(f"[OK] Database already has {cnt} ledgers and {ssr_cnt} SSR tickets. Data is ready!")
                # Ensure at least one Super Admin exists
                try:
                    from django.contrib.auth.hashers import make_password
                    pwd_hash = make_password("admin123")
                    cursor.execute("""
                        INSERT INTO `AppUsers` (`full_name`, `email`, `role`, `branch_name`, `is_super_admin`, `is_active`, `password_hash`, `created_at`, `updated_at`)
                        VALUES ('Ananya Krishnan', 'ananya.krishnan@travelagency.com', 'Administrator', 'Delhi HQ', 1, 1, %s, NOW(), NOW()),
                               ('Administrator', 'admin@travelagency.com', 'Super Admin', 'Delhi HQ', 1, 1, %s, NOW(), NOW())
                        ON DUPLICATE KEY UPDATE `is_super_admin` = 1, `is_active` = 1, `password_hash` = VALUES(`password_hash`);
                    """, [pwd_hash, pwd_hash])
                    print("[OK] Seeded/updated Super Admin users with admin123 password.")
                except Exception as e:
                    print(f"[INFO] AppUsers check: {e}")
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

    # Split statements properly (avoid splitting semicolons inside string literals/base64)
    statements = []
    current = []
    for line in sql_content.splitlines():
        line_s = line.strip()
        if not line_s or line_s.startswith("--") or line_s.upper().startswith("USE "):
            continue
        current.append(line_s)
        if line_s.endswith(";"):
            stmt = " ".join(current).rstrip(";").strip()
            if stmt:
                statements.append(stmt)
            current = []
    if current:
        stmt = " ".join(current).rstrip(";").strip()
        if stmt:
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
        for tbl in ["Ledgers", "Ledger_Groups", "AL_Tickets", "AL_TicketLines", "Rescheduled_Al_Ticket", "Cancellation_AL_Tickets", "JournalVoucher", "Vouchers", "CompanyMaster"]:
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

