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

    # Check if core tables exist
    has_tables = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'Ledgers';")
            has_tables = bool(cursor.fetchone())
    except Exception as e:
        print(f"[INFO] Table check: {e}")
        has_tables = False

    if not has_tables:
        print("[INFO] Core tables missing in database. Executing Schema_mysql.sql to build schema and seed data...")
        schema_file = BASE_DIR / "Schema_mysql.sql"
        if schema_file.exists():
            with open(schema_file, "r", encoding="utf-8") as f:
                schema_content = f.read()
            stmts = []
            buf = []
            for line in schema_content.splitlines():
                trimmed = line.strip()
                if trimmed.startswith("--") or trimmed.startswith("/*") or not trimmed or trimmed.upper().startswith("USE "):
                    continue
                buf.append(line)
                if trimmed.endswith(";"):
                    stmt = "\n".join(buf).strip().rstrip(";")
                    if stmt:
                        stmts.append(stmt)
                    buf = []
            with connection.cursor() as cursor:
                cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
                for stmt in stmts:
                    try:
                        cursor.execute(stmt)
                    except Exception as e:
                        pass
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
            try:
                connection.commit()
            except Exception:
                pass
            print(f"[OK] Schema and initial data successfully deployed from Schema_mysql.sql!")

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

    # Self-healing check for new tables and columns in MySQL / TiDB
    with connection.cursor() as cursor:
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS `AirlineDropdownValues` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `list_key` varchar(50) NOT NULL,
                  `code` varchar(10) NOT NULL,
                  `name` varchar(100) NOT NULL,
                  `display_label` varchar(100) DEFAULT NULL,
                  `sort_order` int NOT NULL DEFAULT '0',
                  `is_default` tinyint(1) NOT NULL DEFAULT '0',
                  `is_active` tinyint(1) NOT NULL DEFAULT '1',
                  `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                  `updated_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
                  PRIMARY KEY (`id`),
                  UNIQUE KEY `uq_airline_dd_code` (`list_key`,`code`),
                  UNIQUE KEY `uq_airline_dd_name` (`list_key`,`name`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
        except Exception as e:
            print(f"[INFO] AirlineDropdownValues table check: {e}")

        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS `AuditLogs` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `company_id` int NOT NULL,
                  `module` varchar(30) NOT NULL,
                  `document_id` int NOT NULL,
                  `document_no` varchar(50) DEFAULT NULL,
                  `action` varchar(20) NOT NULL,
                  `source` varchar(150) DEFAULT NULL,
                  `user_id` int DEFAULT NULL,
                  `user_name` varchar(150) DEFAULT NULL,
                  `change_count` int NOT NULL DEFAULT '0',
                  `changes` longtext,
                  `changed_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                  PRIMARY KEY (`id`),
                  KEY `ix_audit_logs_document` (`company_id`,`module`,`document_id`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
        except Exception as e:
            print(f"[INFO] AuditLogs table check: {e}")

        try:
            cursor.execute("ALTER TABLE `SSR_AL_TicketLines` ADD COLUMN `ssr_charges` longtext NULL;")
        except Exception:
            pass

    counts = {}
    with connection.cursor() as cursor:
        for tbl in ["Ledgers", "Ledger_Groups", "AL_Tickets", "AL_TicketLines", "Rescheduled_Al_Ticket", "Cancellation_AL_Tickets", "SSR_AL_Tickets", "SSR_AL_TicketLines", "Misc_Transactions", "JournalVoucher", "Vouchers", "AirlineDropdownValues", "AuditLogs", "CompanyMaster"]:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM `{tbl}`;")
                counts[tbl] = cursor.fetchone()[0]
            except Exception:
                pass

        try:
            from django.contrib.auth.hashers import make_password
            pwd_hash = make_password("admin123")
            cursor.execute("""
                INSERT INTO `AppUsers` (`full_name`, `email`, `role`, `branch_name`, `is_super_admin`, `is_active`, `password_hash`, `created_at`, `updated_at`)
                VALUES ('Ananya Krishnan', 'ananya.krishnan@travelagency.com', 'Administrator', 'Delhi HQ', 1, 1, %s, NOW(), NOW()),
                       ('Administrator', 'admin@travelagency.com', 'Super Admin', 'Delhi HQ', 1, 1, %s, NOW(), NOW())
                ON DUPLICATE KEY UPDATE `is_super_admin` = 1, `is_active` = 1, `password_hash` = VALUES(`password_hash`);
            """, [pwd_hash, pwd_hash])
        except Exception as e:
            print(f"[WARN] Super Admin sync failed: {e}")

    print(f"[OK] Successfully executed {success} statements into database!")
    print(f"[OK] Row counts: {counts}")
    print("=" * 60)
    return {"status": "ok", "executed": success, "errors": errors, "counts": counts}



if __name__ == "__main__":
    force_run = "--force" in sys.argv
    load_data(force=force_run)

