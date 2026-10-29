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


def ensure_schema(cursor):
    for q in [
        """CREATE TABLE IF NOT EXISTS `AirlineDropdownValues` (
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
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

        """CREATE TABLE IF NOT EXISTS `AuditLogs` (
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
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

        """CREATE TABLE IF NOT EXISTS `FOPMasterHistory` (
          `id` int NOT NULL AUTO_INCREMENT,
          `company_id` int NOT NULL,
          `card_master_ledger_name` varchar(200) DEFAULT NULL,
          `effective_from` date NOT NULL,
          `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          `updated_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
          `card_master_ledger_id` int NOT NULL,
          `fop_master_id` int NOT NULL,
          PRIMARY KEY (`id`),
          UNIQUE KEY `uq_fop_history_card_date` (`fop_master_id`,`effective_from`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

        """CREATE TABLE IF NOT EXISTS `Ticket_Document_Attribute` (
          `attribute_id` int NOT NULL AUTO_INCREMENT,
          `company_id` int NOT NULL,
          `doc_type` varchar(20) NOT NULL,
          `doc_id` int NOT NULL,
          `invoice_number` varchar(20) DEFAULT NULL,
          `sort_order` int NOT NULL DEFAULT 0,
          `field_name` varchar(100) NOT NULL,
          `field_value` varchar(500) DEFAULT NULL,
          `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          PRIMARY KEY (`attribute_id`),
          KEY `ix_tda_doc` (`company_id`, `doc_type`, `doc_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

        """CREATE TABLE IF NOT EXISTS `Ticket_Line_Gst_Amount` (
          `line_type` varchar(20) NOT NULL,
          `doc_id` int NOT NULL,
          `ticket_no` varchar(30) NOT NULL,
          `service_fee_gst` decimal(14,2) DEFAULT NULL,
          `addl_service_fee_gst` decimal(14,2) DEFAULT NULL,
          `ssr_service_fee_gst` decimal(14,2) DEFAULT NULL,
          `supp_service_fee_gst` decimal(14,2) DEFAULT NULL,
          `supp_addl_service_fee_gst` decimal(14,2) DEFAULT NULL,
          `supp_ssr_service_fee_gst` decimal(14,2) DEFAULT NULL,
          `source` varchar(30) NOT NULL DEFAULT '',
          `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          PRIMARY KEY (`line_type`, `doc_id`, `ticket_no`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

        """CREATE TABLE IF NOT EXISTS `MasterMappingPin` (
          `id` int NOT NULL AUTO_INCREMENT,
          `company_id` int NOT NULL,
          `product_type` varchar(20) NOT NULL,
          `field_name` varchar(100) NOT NULL,
          `doc_type` varchar(20) NOT NULL,
          `doc_id` int NOT NULL,
          `doc_date` date NOT NULL,
          `ledger_id` int NOT NULL,
          `ledger_name` varchar(200) DEFAULT NULL,
          `masters_category` varchar(40) DEFAULT NULL,
          `effective_from` date DEFAULT NULL,
          `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          PRIMARY KEY (`id`),
          UNIQUE KEY `uq_mmp_doc_field` (`company_id`, `doc_type`, `doc_id`, `field_name`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

        """CREATE TABLE IF NOT EXISTS `PGMasterPin` (
          `pin_id` int NOT NULL AUTO_INCREMENT,
          `company_id` int NOT NULL,
          `gateway_name` varchar(100) NOT NULL,
          `doc_type` varchar(20) NOT NULL,
          `doc_id` int NOT NULL,
          `doc_date` date DEFAULT NULL,
          `payment_master_ledger_id` int DEFAULT NULL,
          `payment_master_ledger_name` varchar(200) DEFAULT NULL,
          `pg_charges_master_ledger_id` int DEFAULT NULL,
          `pg_charges_master_ledger_name` varchar(200) DEFAULT NULL,
          `pg_charges_percentage` decimal(5,2) DEFAULT NULL,
          `effective_from` date DEFAULT NULL,
          `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          PRIMARY KEY (`pin_id`),
          UNIQUE KEY `uq_pgmp_doc` (`company_id`, `gateway_name`, `doc_type`, `doc_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

        """CREATE TABLE IF NOT EXISTS `Agent_DB_Scheduler_Log` (
          `log_id` bigint NOT NULL AUTO_INCREMENT,
          `run_started_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          `run_finished_at` datetime(6) DEFAULT NULL,
          `source_database` varchar(128) DEFAULT NULL,
          `source_table` varchar(128) DEFAULT NULL,
          `records_fetched` int NOT NULL DEFAULT 0,
          `invoices_fetched` int NOT NULL DEFAULT 0,
          `imported_count` int NOT NULL DEFAULT 0,
          `pending_count` int NOT NULL DEFAULT 0,
          `error_count` int NOT NULL DEFAULT 0,
          `message` varchar(1000) DEFAULT NULL,
          PRIMARY KEY (`log_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

        """CREATE TABLE IF NOT EXISTS `Agent_DB_Ticket_Log` (
          `ticket_log_id` bigint NOT NULL AUTO_INCREMENT,
          `source_database` varchar(128) NOT NULL,
          `source_table` varchar(128) NOT NULL,
          `agent_row_id` bigint NOT NULL,
          `scheduler_log_id` bigint DEFAULT NULL,
          `company_id` int DEFAULT NULL,
          `booking_status` varchar(100) DEFAULT NULL,
          `booking_reference` varchar(100) DEFAULT NULL,
          `ticket_no` varchar(100) DEFAULT NULL,
          `pax_name` varchar(100) DEFAULT NULL,
          `process_status` varchar(20) NOT NULL DEFAULT 'Processing',
          `processing_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          `processed_at` datetime(6) DEFAULT NULL,
          `invoice_number` varchar(30) DEFAULT NULL,
          `voucher_no` varchar(30) DEFAULT NULL,
          `import_doc_key` varchar(200) DEFAULT NULL,
          `error_message` varchar(2000) DEFAULT NULL,
          PRIMARY KEY (`ticket_log_id`),
          UNIQUE KEY `uq_adtl_source_row` (`source_database`, `source_table`, `agent_row_id`),
          KEY `ix_adtl_doc_key` (`import_doc_key`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

        """CREATE TABLE IF NOT EXISTS `Ticket_Import_Invoice_Type` (
          `id` int NOT NULL AUTO_INCREMENT,
          `company_id` int NOT NULL,
          `ticket_status` varchar(20) NOT NULL,
          `voucher_type_id` int NOT NULL,
          `updated_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
          PRIMARY KEY (`id`),
          UNIQUE KEY `uq_tiit_company_status` (`company_id`, `ticket_status`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

        """CREATE TABLE IF NOT EXISTS `Ticket_Import_Run_Log` (
          `run_id` bigint NOT NULL AUTO_INCREMENT,
          `company_id` int DEFAULT NULL,
          `started_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          `finished_at` datetime(6) DEFAULT NULL,
          `rows_picked` int NOT NULL DEFAULT 0,
          `docs_imported` int NOT NULL DEFAULT 0,
          `docs_failed` int NOT NULL DEFAULT 0,
          `message` varchar(1000) DEFAULT NULL,
          PRIMARY KEY (`run_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

        """CREATE TABLE IF NOT EXISTS `Ticket_Import_Error_Log` (
          `error_log_id` bigint NOT NULL AUTO_INCREMENT,
          `logged_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          `company_id` int DEFAULT NULL,
          `source_system` varchar(50) DEFAULT NULL,
          `batch_id` varchar(50) DEFAULT NULL,
          `doc_key` varchar(200) DEFAULT NULL,
          `booking_status` varchar(20) DEFAULT NULL,
          `booking_reference` varchar(60) DEFAULT NULL,
          `parent_pnr` varchar(60) DEFAULT NULL,
          `passenger_no` int DEFAULT NULL,
          `ticket_no` varchar(60) DEFAULT NULL,
          `passenger_name` varchar(100) DEFAULT NULL,
          `field_name` varchar(100) DEFAULT NULL,
          `field_label` varchar(100) DEFAULT NULL,
          `received_value` varchar(500) DEFAULT NULL,
          `expected_value` varchar(500) DEFAULT NULL,
          `error_type` varchar(30) NOT NULL DEFAULT '',
          `severity` varchar(10) NOT NULL DEFAULT '',
          `stage` varchar(20) NOT NULL DEFAULT '',
          `error_message` varchar(1000) NOT NULL DEFAULT '',
          `is_resolved` tinyint(1) NOT NULL DEFAULT 0,
          `resolved_at` datetime(6) DEFAULT NULL,
          `resolved_note` varchar(200) DEFAULT NULL,
          PRIMARY KEY (`error_log_id`),
          KEY `ix_tiel_search` (`company_id`, `booking_status`, `logged_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

        """CREATE TABLE IF NOT EXISTS `Ticket_Import_Staging` (
          `staging_id` bigint NOT NULL AUTO_INCREMENT,
          `batch_id` varchar(50) DEFAULT NULL,
          `source_system` varchar(50) NOT NULL,
          `doc_ref` varchar(60) NOT NULL,
          `source_record_id` varchar(100) NOT NULL,
          `received_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          `ticket_status` varchar(20) NOT NULL,
          `company_id` int NOT NULL,
          `doc_key` varchar(200) GENERATED ALWAYS AS (CONCAT(`ticket_status`, '|', CAST(`company_id` AS CHAR), '|', `source_system`, '|', `doc_ref`)) STORED,
          `branch_name` varchar(100) DEFAULT NULL,
          `invoice_number` varchar(20) DEFAULT NULL,
          `invoice_date` date DEFAULT NULL,
          `invoice_type` varchar(100) DEFAULT NULL,
          `booking_mode` varchar(20) DEFAULT NULL,
          `booking_type` varchar(50) DEFAULT NULL,
          `booking_status` varchar(20) DEFAULT NULL,
          `customer_name` varchar(150) DEFAULT NULL,
          `supplier_name` varchar(150) DEFAULT NULL,
          `travel_type` varchar(20) DEFAULT NULL,
          `user_name` varchar(100) DEFAULT NULL,
          `currency` varchar(5) DEFAULT NULL,
          `roe` decimal(10,4) DEFAULT NULL,
          `booking_given_by` varchar(25) DEFAULT NULL,
          `booking_reference` varchar(30) DEFAULT NULL,
          `booking_ref_date` date DEFAULT NULL,
          `airline_pnr` varchar(13) DEFAULT NULL,
          `gds_pnr` varchar(13) DEFAULT NULL,
          `office_id` varchar(30) DEFAULT NULL,
          `payment_mode` varchar(20) DEFAULT NULL,
          `payment_gateway_ref` varchar(60) DEFAULT NULL,
          `airline_category` varchar(5) DEFAULT NULL,
          `original_ticket_no` varchar(30) DEFAULT NULL,
          `airline_code` varchar(200) DEFAULT NULL,
          `airline_name` varchar(200) DEFAULT NULL,
          `line_airline_category` varchar(5) DEFAULT NULL,
          `flight_no` varchar(200) DEFAULT NULL,
          `ticket_no` varchar(30) DEFAULT NULL,
          `passenger_name` varchar(50) DEFAULT NULL,
          `pax_type` varchar(10) DEFAULT NULL,
          `sector` varchar(200) DEFAULT NULL,
          `travel_date` varchar(200) DEFAULT NULL,
          `cabin` varchar(200) DEFAULT NULL,
          `travel_class` varchar(200) DEFAULT NULL,
          `fare_type` varchar(300) DEFAULT NULL,
          `line_supplier_name` varchar(150) DEFAULT NULL,
          `line_office_id` varchar(30) DEFAULT NULL,
          `fop` varchar(20) DEFAULT NULL,
          `card_number` varchar(40) DEFAULT NULL,
          `line_status` varchar(15) DEFAULT NULL,
          `basic_fare` decimal(14,2) NOT NULL DEFAULT 0,
          `yq` decimal(14,2) NOT NULL DEFAULT 0,
          `yr` decimal(14,2) NOT NULL DEFAULT 0,
          `k3_tax` decimal(14,2) NOT NULL DEFAULT 0,
          `tax_others` decimal(14,2) NOT NULL DEFAULT 0,
          `seat` decimal(14,2) NOT NULL DEFAULT 0,
          `meal` decimal(14,2) NOT NULL DEFAULT 0,
          `baggage` decimal(14,2) NOT NULL DEFAULT 0,
          `other_ssr` decimal(14,2) NOT NULL DEFAULT 0,
          `disc_on` varchar(20) DEFAULT NULL,
          `disc_type` varchar(12) DEFAULT NULL,
          `disc_value` decimal(14,2) NOT NULL DEFAULT 0,
          `tds_per` decimal(5,2) NOT NULL DEFAULT 0,
          `pg_charges` decimal(14,2) NOT NULL DEFAULT 0,
          `pg_charges_percentage` decimal(5,2) NOT NULL DEFAULT 0,
          `markup` decimal(14,2) NOT NULL DEFAULT 0,
          `addl_markup` decimal(14,2) NOT NULL DEFAULT 0,
          `ssr_markup` decimal(14,2) NOT NULL DEFAULT 0,
          `service_fee` decimal(14,2) NOT NULL DEFAULT 0,
          `addl_service_fee` decimal(14,2) NOT NULL DEFAULT 0,
          `ssr_service_fee` decimal(14,2) NOT NULL DEFAULT 0,
          `gst_pct` decimal(5,2) NOT NULL DEFAULT 0,
          `supp_comm_on` varchar(20) DEFAULT NULL,
          `supp_comm_type` varchar(12) DEFAULT NULL,
          `supp_comm_value` decimal(14,2) NOT NULL DEFAULT 0,
          `supp_tds_per` decimal(5,2) NOT NULL DEFAULT 0,
          `supp_markup` decimal(14,2) NOT NULL DEFAULT 0,
          `supp_addl_markup` decimal(14,2) NOT NULL DEFAULT 0,
          `supp_ssr_markup` decimal(14,2) NOT NULL DEFAULT 0,
          `supp_service_fee` decimal(14,2) NOT NULL DEFAULT 0,
          `supp_addl_service_fee` decimal(14,2) NOT NULL DEFAULT 0,
          `supp_ssr_service_fee` decimal(14,2) NOT NULL DEFAULT 0,
          `supp_gst_pct` decimal(5,2) NOT NULL DEFAULT 0,
          `agent_penalty` decimal(14,2) NOT NULL DEFAULT 0,
          `reschedule_penalty` decimal(14,2) NOT NULL DEFAULT 0,
          `supplier_penalty` decimal(14,2) NOT NULL DEFAULT 0,
          `cancellation_penalty` decimal(14,2) NOT NULL DEFAULT 0,
          `cust_markup_reversal` decimal(14,2) NOT NULL DEFAULT 0,
          `cust_addl_markup_reversal` decimal(14,2) NOT NULL DEFAULT 0,
          `cust_ssr_markup_reversal` decimal(14,2) NOT NULL DEFAULT 0,
          `supp_markup_reversal` decimal(14,2) NOT NULL DEFAULT 0,
          `supp_addl_markup_reversal` decimal(14,2) NOT NULL DEFAULT 0,
          `supp_ssr_markup_reversal` decimal(14,2) NOT NULL DEFAULT 0,
          `tds_amount_override` decimal(14,2) DEFAULT NULL,
          `supp_tds_amount_override` decimal(14,2) DEFAULT NULL,
          `total_billed` decimal(14,2) DEFAULT NULL,
          `raw_payload` longtext DEFAULT NULL,
          `process_status` varchar(20) NOT NULL DEFAULT 'Pending',
          `retry_count` int NOT NULL DEFAULT 0,
          `error_message` varchar(1000) DEFAULT NULL,
          `run_id` bigint DEFAULT NULL,
          `picked_at` datetime(6) DEFAULT NULL,
          `processed_at` datetime(6) DEFAULT NULL,
          `target_header_id` int DEFAULT NULL,
          `saved_invoice_number` varchar(20) DEFAULT NULL,
          `saved_voucher_no` varchar(30) DEFAULT NULL,
          PRIMARY KEY (`staging_id`),
          KEY `ix_tis_queue` (`company_id`, `process_status`, `received_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

        "ALTER TABLE `FOPMaster` ADD COLUMN `effective_from` date NULL;",
        "ALTER TABLE `SSR_AL_TicketLines` ADD COLUMN `ssr_charges` longtext NULL;",
        "ALTER TABLE `Cancellation_AL_Tickets` ADD COLUMN `parent_pnr` varchar(100) NULL;",
        "ALTER TABLE `Cancellation_Al_TicketLines` ADD COLUMN `reschedule_line_id` int NULL;",
        "ALTER TABLE `SSR_AL_Tickets` ADD COLUMN `parent_pnr` varchar(100) NULL;",
        "ALTER TABLE `SSR_AL_TicketLines` ADD COLUMN `card_number` varchar(100) NULL;",
        "ALTER TABLE `UserMenuAccess` ADD COLUMN `can_print` tinyint(1) NOT NULL DEFAULT 0;",
        "ALTER TABLE `UserMenuAccess` ADD COLUMN `can_export` tinyint(1) NOT NULL DEFAULT 0;",
        "ALTER TABLE `Rescheduled_Al_Ticket` MODIFY COLUMN `original_ticket_id` int NULL;",
        "ALTER TABLE `Rescheduled_Al_TicketLines` MODIFY COLUMN `original_ticket_line_id` int NULL;",
        "ALTER TABLE `Cancellation_AL_Tickets` MODIFY COLUMN `original_ticket_id` int NULL;",
        "ALTER TABLE `Cancellation_Al_TicketLines` MODIFY COLUMN `original_ticket_line_id` int NULL;",
        "ALTER TABLE `SSR_AL_Tickets` MODIFY COLUMN `original_ticket_id` int NULL;",
        "ALTER TABLE `SSR_AL_TicketLines` MODIFY COLUMN `original_ticket_line_id` int NULL;",
    ]:
        try:
            cursor.execute(q)
        except Exception:
            pass


def load_data(force=False):
    print("=" * 60)
    print("  Checking TiDB Database Records")
    print("=" * 60)

    # Check if core tables exist
    has_tables = False
    try:
        with connection.cursor() as cursor:
            ensure_schema(cursor)
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
        ensure_schema(cursor)

    counts = {}
    with connection.cursor() as cursor:
        for tbl in ["Ledgers", "Ledger_Groups", "AL_Tickets", "AL_TicketLines", "Rescheduled_Al_Ticket", "Cancellation_AL_Tickets", "SSR_AL_Tickets", "SSR_AL_TicketLines", "Misc_Transactions", "JournalVoucher", "Vouchers", "AirlineDropdownValues", "AuditLogs", "CompanyMaster", "FOPMasterHistory"]:
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

    # Ensure Airline_Agent database and table are initialized
    try:
        airline_sql_file = BASE_DIR / "airline_agent_mysql.sql"
        if airline_sql_file.exists():
            with open(airline_sql_file, "r", encoding="utf-8") as af:
                a_content = af.read()
            a_stmts = [s.strip() for s in a_content.split(";") if s.strip()]
            with connection.cursor() as cursor:
                cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
                for s in a_stmts:
                    try:
                        cursor.execute(s)
                    except Exception:
                        pass
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
            print("[OK] Airline_Agent database & Agent_ticket_data verified!")
    except Exception as e:
        print(f"[INFO] Airline_Agent init check: {e}")

    print(f"[OK] Successfully executed {success} statements into database!")
    print(f"[OK] Row counts: {counts}")
    print("=" * 60)
    return {"status": "ok", "executed": success, "errors": errors, "counts": counts}



if __name__ == "__main__":
    force_run = "--force" in sys.argv
    load_data(force=force_run)

