#!/usr/bin/env python
"""
Convert MSSQL exported scripts (UTF-16) to MySQL/TiDB compatible SQL scripts.
- Airline_Agentscript.sql -> airline_agent_mysql.sql
- 29.10.26script.sql      -> converted_inserts.sql (and Schema_mysql.sql updates)
"""

import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
BACKUP_DIR = Path(r"D:\MANOHARAN T\accounting soft backeps dep\Accounting Software Live 29.10.26 morning originol")

AIRLINE_AGENT_SRC = BACKUP_DIR / "Airline_Agentscript.sql"
MAIN_SCRIPT_SRC = BACKUP_DIR / "29.10.26script.sql"


def convert_val(val_str):
    # CAST(N'...' AS DateTime2 / DateTimeOffset / Date)
    val_str = re.sub(
        r"CAST\s*\(\s*N?'([^']+)'\s+AS\s+DateTime(?:2|Offset)?(?:\(\d+\))?\s*\)",
        lambda m: "'" + re.sub(r'(\.\d{6})\d+', r'\1', m.group(1).replace("T", " ").split("+")[0].strip()) + "'",
        val_str,
        flags=re.IGNORECASE
    )
    val_str = re.sub(
        r"CAST\s*\(\s*N?'([^']+)'\s+AS\s+Date\s*\)",
        lambda m: f"'{m.group(1)}'",
        val_str,
        flags=re.IGNORECASE
    )
    # CAST(... AS Decimal(...) / Numeric(...))
    val_str = re.sub(
        r"CAST\s*\(\s*([0-9\.\-]+)\s+AS\s+(?:Decimal|Numeric)\([^)]+\)\s*\)",
        r"\1",
        val_str,
        flags=re.IGNORECASE
    )
    # CAST(... AS INT / BIT)
    val_str = re.sub(
        r"CAST\s*\(\s*([0-9]+)\s+AS\s+(?:INT|BIT)\s*\)",
        r"\1",
        val_str,
        flags=re.IGNORECASE
    )
    # CAST(N'...' AS NVARCHAR(...))
    val_str = re.sub(
        r"CAST\s*\(\s*N?'([^']*)'\s+AS\s+N?VARCHAR(?:\([^)]*\))?\s*\)",
        lambda m: f"'{m.group(1)}'",
        val_str,
        flags=re.IGNORECASE
    )
    # N'...' -> '...'
    val_str = re.sub(r"(?<![A-Za-z0-9_])N'", "'", val_str)
    return val_str


def convert_insert_statement(line):
    # Match INSERT [dbo].[TableName] ([col1], ...) VALUES (...)
    # or INSERT INTO [dbo].[TableName] ...
    m = re.match(r"^\s*INSERT\s+(?:INTO\s+)?\[dbo\]\.\[(\w+)\]\s*\((.*?)\)\s*VALUES\s*\((.*)\)\s*;?\s*$", line, re.DOTALL | re.IGNORECASE)
    if not m:
        # Check if INSERT without [dbo]
        m = re.match(r"^\s*INSERT\s+(?:INTO\s+)?`?(\w+)`?\s*\((.*?)\)\s*VALUES\s*\((.*)\)\s*;?\s*$", line, re.DOTALL | re.IGNORECASE)
        if not m:
            return None
    tbl = m.group(1)
    cols_raw = m.group(2)
    vals_raw = m.group(3)

    # Format columns: [col] -> `col`
    cols = [f"`{c.strip().strip('[]`')}`" for c in cols_raw.split(",") if c.strip()]
    cols_str = ", ".join(cols)

    # Convert values
    converted_vals = convert_val(vals_raw.strip())

    return f"INSERT INTO `{tbl}` ({cols_str}) VALUES ({converted_vals});"


def process_airline_agent():
    print(f"Reading {AIRLINE_AGENT_SRC}...")
    with open(AIRLINE_AGENT_SRC, "r", encoding="utf-16", errors="replace") as f:
        content = f.read()

    lines = content.splitlines()
    inserts = []
    for line in lines:
        line_s = line.strip()
        if line_s.upper().startswith("INSERT"):
            stmt = convert_insert_statement(line_s)
            if stmt:
                inserts.append(stmt)

    print(f"Airline_Agent: Found {len(inserts)} INSERT statements.")

    out_file = BASE_DIR / "airline_agent_mysql.sql"
    with open(out_file, "w", encoding="utf-8") as out:
        out.write("""-- ==========================================================================
-- Airline_Agent Database & Table for MySQL / TiDB
-- ==========================================================================
CREATE DATABASE IF NOT EXISTS `Airline_Agent`;
USE `Airline_Agent`;

CREATE TABLE IF NOT EXISTS `Agent_ticket_data` (
  `agent_row_id` bigint NOT NULL AUTO_INCREMENT,
  `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `company_id` int NOT NULL,
  `booking_status` varchar(100) DEFAULT NULL,
  `booking_type` varchar(100) DEFAULT NULL,
  `customer_id` varchar(100) DEFAULT NULL,
  `travel_type` varchar(100) DEFAULT NULL,
  `user_name` varchar(200) DEFAULT NULL,
  `booking_given_by` varchar(100) DEFAULT NULL,
  `booking_reference` varchar(100) DEFAULT NULL,
  `booking_ref_date` varchar(100) DEFAULT NULL,
  `airline_pnr` varchar(100) DEFAULT NULL,
  `gds_pnr` varchar(100) DEFAULT NULL,
  `payment_mode` varchar(100) DEFAULT NULL,
  `gateway_ref` varchar(100) DEFAULT NULL,
  `fop` varchar(100) DEFAULT NULL,
  `card_number` varchar(100) DEFAULT NULL,
  `parent_pnr` varchar(100) DEFAULT NULL,
  `ticket_no` varchar(100) DEFAULT NULL,
  `original_ticket_no` varchar(100) DEFAULT NULL,
  `pax_name` varchar(100) DEFAULT NULL,
  `pax_type` varchar(100) DEFAULT NULL,
  `airline_category` varchar(100) DEFAULT NULL,
  `sector` varchar(400) DEFAULT NULL,
  `airline_code` varchar(400) DEFAULT NULL,
  `travel_date` varchar(400) DEFAULT NULL,
  `flight_no` varchar(400) DEFAULT NULL,
  `cabin` varchar(400) DEFAULT NULL,
  `class` varchar(400) DEFAULT NULL,
  `fare_type` varchar(400) DEFAULT NULL,
  `office_id` varchar(100) DEFAULT NULL,
  `basic_fare` decimal(18,2) DEFAULT NULL,
  `yq_tax` decimal(18,2) DEFAULT NULL,
  `yr_tax` decimal(18,2) DEFAULT NULL,
  `k3_tax` decimal(18,2) DEFAULT NULL,
  `tax_others` decimal(18,2) DEFAULT NULL,
  `seat_charges` decimal(18,2) DEFAULT NULL,
  `meal_charges` decimal(18,2) DEFAULT NULL,
  `baggage_charges` decimal(18,2) DEFAULT NULL,
  `other_ssr` decimal(18,2) DEFAULT NULL,
  `cust_discount_amount` decimal(18,2) DEFAULT NULL,
  `cust_tds_amount` decimal(18,2) DEFAULT NULL,
  `cust_markup` decimal(18,2) DEFAULT NULL,
  `cust_addl_markup` decimal(18,2) DEFAULT NULL,
  `cust_ssr_markup` decimal(18,2) DEFAULT NULL,
  `cust_service_fee` decimal(18,2) DEFAULT NULL,
  `cust_addl_service_fee` decimal(18,2) DEFAULT NULL,
  `cust_ssr_service_fee` decimal(18,2) DEFAULT NULL,
  `cust_service_fee_gst` decimal(18,2) DEFAULT NULL,
  `cust_ssr_service_fee_gst` decimal(18,2) DEFAULT NULL,
  `cust_addl_service_fee_gst` decimal(18,2) DEFAULT NULL,
  `supp_commission_amount` decimal(18,2) DEFAULT NULL,
  `supp_tds_amount` decimal(18,2) DEFAULT NULL,
  `supp_markup` decimal(18,2) DEFAULT NULL,
  `supp_addl_markup` decimal(18,2) DEFAULT NULL,
  `supp_ssr_markup` decimal(18,2) DEFAULT NULL,
  `supp_service_fee` decimal(18,2) DEFAULT NULL,
  `supp_addl_service_fee` decimal(18,2) DEFAULT NULL,
  `supp_ssr_service_fee` decimal(18,2) DEFAULT NULL,
  `supp_service_fee_gst` decimal(18,2) DEFAULT NULL,
  `supp_ssr_service_fee_gst` decimal(18,2) DEFAULT NULL,
  `supp_addl_service_fee_gst` decimal(18,2) DEFAULT NULL,
  `supplier_penalty` decimal(18,2) DEFAULT NULL,
  `agent_penalty` decimal(18,2) DEFAULT NULL,
  `penalty_amount` decimal(18,2) DEFAULT NULL,
  `cust_markup_reversal` decimal(18,2) DEFAULT NULL,
  `cust_addl_markup_reversal` decimal(18,2) DEFAULT NULL,
  `cust_ssr_markup_reversal` decimal(18,2) DEFAULT NULL,
  `supp_markup_reversal` decimal(18,2) DEFAULT NULL,
  `supp_addl_markup_reversal` decimal(18,2) DEFAULT NULL,
  `supp_ssr_markup_reversal` decimal(18,2) DEFAULT NULL,
  `emd_ticket_no_baggage` varchar(100) DEFAULT NULL,
  `emd_ticket_no_meal` varchar(100) DEFAULT NULL,
  `emd_ticket_no_seat` varchar(100) DEFAULT NULL,
  `emd_ticket_no_other_ssr` varchar(100) DEFAULT NULL,
  `ssr_baggage_details` varchar(100) DEFAULT NULL,
  `ssr_meal_details` varchar(100) DEFAULT NULL,
  `ssr_seat_details` varchar(100) DEFAULT NULL,
  `ssr_other_details` varchar(100) DEFAULT NULL,
  PRIMARY KEY (`agent_row_id`),
  KEY `ix_agent_invoice` (`company_id`, `booking_status`, `booking_reference`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SET FOREIGN_KEY_CHECKS = 0;
DELETE FROM `Agent_ticket_data`;
""")
        for ins in inserts:
            out.write(ins + "\n")
        out.write("SET FOREIGN_KEY_CHECKS = 1;\n")

    print(f"Saved {out_file} ({len(inserts)} rows)")


def process_main_script():
    print(f"Reading {MAIN_SCRIPT_SRC} (5.4MB)...")
    with open(MAIN_SCRIPT_SRC, "r", encoding="utf-16", errors="replace") as f:
        content = f.read()

    lines = content.splitlines()
    table_inserts = {}
    total_found = 0

    # Skip django migrations and django content types
    skip_tables = {"django_content_type", "django_migrations"}

    for line in lines:
        line_s = line.strip()
        if line_s.upper().startswith("INSERT"):
            stmt = convert_insert_statement(line_s)
            if stmt:
                # get table name
                m = re.match(r"^INSERT INTO `(\w+)`", stmt)
                if m:
                    tbl = m.group(1)
                    if tbl in skip_tables:
                        continue
                    table_inserts.setdefault(tbl, []).append(stmt)
                    total_found += 1

    print(f"Main DB: Found {total_found} INSERT statements across {len(table_inserts)} tables:")
    for tbl, ins_list in sorted(table_inserts.items()):
        print(f"  - {tbl}: {len(ins_list)} rows")

    # Order of deletion / insertion to avoid foreign key dependency conflicts
    tables_order = [
        "AuditLogs",
        "Agent_DB_Ticket_Log",
        "Agent_DB_Scheduler_Log",
        "Ticket_Line_Gst_Amount",
        "Ticket_Document_Attribute",
        "Ticket_Import_Error_Log",
        "Ticket_Import_Invoice_Type",
        "Ticket_Import_Run_Log",
        "Ticket_Import_Staging",
        "AirlineDropdownValues",
        "UserMenuAccess",
        "AppUsers",
        "MenuMaster",
        "Vouchers",
        "JournalVoucher",
        "Misc_Transactions",
        "SSR_AL_TicketLines",
        "SSR_AL_Tickets",
        "Cancellation_Al_TicketLines",
        "Cancellation_AL_Tickets",
        "Rescheduled_Al_TicketLines",
        "Rescheduled_Al_Ticket",
        "AL_TicketLines",
        "AL_Tickets",
        "MasterMappingPin",
        "PGMasterPin",
        "MasterMappingHistory",
        "MasterMapping",
        "SupplierCommissionRules",
        "PGMasterHistory",
        "PGMaster",
        "FOPMasterHistory",
        "FOPMaster",
        "VoucherType",
        "Ledgers",
        "Ledger_Groups",
        "CompanyMaster"
    ]

    out_file = BASE_DIR / "converted_inserts.sql"
    with open(out_file, "w", encoding="utf-8") as out:
        out.write("""-- ==========================================================================
-- Voyager ERP - TiDB / MySQL Database Records
-- Auto-converted from 29.10.26script.sql (MSSQL -> MySQL / TiDB)
-- ==========================================================================
SET FOREIGN_KEY_CHECKS = 0;

-- 1. Clear existing application data
""")
        for tbl in tables_order:
            out.write(f"DELETE FROM `{tbl}`;\n")

        out.write("\n-- 2. Insert updated business records\n\n")

        # Reverse tables_order for insertion
        for tbl in reversed(tables_order):
            if tbl in table_inserts:
                out.write(f"-- Table: {tbl} ({len(table_inserts[tbl])} rows)\n")
                for ins in table_inserts[tbl]:
                    out.write(ins + "\n")
                out.write("\n")

        # Any remaining tables not in tables_order
        for tbl, ins_list in table_inserts.items():
            if tbl not in tables_order:
                out.write(f"-- Table: {tbl} ({len(ins_list)} rows)\n")
                for ins in ins_list:
                    out.write(ins + "\n")
                out.write("\n")

        out.write("SET FOREIGN_KEY_CHECKS = 1;\n")

    print(f"Saved {out_file} ({total_found} rows)")


if __name__ == "__main__":
    process_airline_agent()
    process_main_script()

