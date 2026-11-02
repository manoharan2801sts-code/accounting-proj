import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
AGENT_SCRIPT = Path(r"D:\MANOHARAN T\accounting soft backeps dep\2.11.26 morng live\Accounting Software Live\agent 2.11.26script.sql")

def main():
    with open(AGENT_SCRIPT, "r", encoding="utf-16") as f:
        text = f.read()

    # 1. Parse all 95 columns from CREATE TABLE
    col_matches = re.findall(r'^\s*\[([a-zA-Z0-9_]+)\]\s+\[([a-zA-Z0-9_]+)\](?:\((.*?)\))?\s*(NOT NULL|NULL)?', text, re.MULTILINE)
    print(f"Total columns found: {len(col_matches)}")

    col_defs = []
    for col, dtype, size, nullable in col_matches:
        if col.lower() == 'agent_row_id':
            col_defs.append("  `agent_row_id` bigint NOT NULL AUTO_INCREMENT")
            continue
        dtype_low = dtype.lower()
        null_str = "NOT NULL" if nullable == "NOT NULL" else "DEFAULT NULL"
        if dtype_low == 'datetime2':
            my_type = "datetime(6)"
            if 'default' in text.lower():
                null_str = "NOT NULL DEFAULT CURRENT_TIMESTAMP(6)"
        elif dtype_low == 'nvarchar':
            my_type = f"varchar({size})" if size else "varchar(255)"
        elif dtype_low == 'decimal':
            my_type = f"decimal({size})" if size else "decimal(18,2)"
        elif dtype_low == 'int':
            my_type = "int"
        elif dtype_low == 'bigint':
            my_type = "bigint"
        else:
            my_type = dtype
        col_defs.append(f"  `{col}` {my_type} {null_str}")

    col_defs.append("  PRIMARY KEY (`agent_row_id`)")
    col_defs.append("  KEY `ix_agent_invoice` (`company_id`, `booking_status`, `booking_reference`)")

    create_table_sql = (
        "CREATE DATABASE IF NOT EXISTS `Airline_Agent`;\n\n"
        "DROP TABLE IF EXISTS `Airline_Agent`.`Agent_ticket_data`;\n"
        "CREATE TABLE `Airline_Agent`.`Agent_ticket_data` (\n"
        + ",\n".join(col_defs)
        + "\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;\n"
    )

    # 2. Extract and transform all INSERT statements
    lines = [l for l in text.splitlines() if l.startswith("INSERT [dbo].[Agent_ticket_data]")]
    print(f"Total INSERT statements found in agent script: {len(lines)}")

    def transform_sql(stmt):
        s = re.sub(r"INSERT\s+\[dbo\]\.\[Agent_ticket_data\]", "REPLACE INTO `Airline_Agent`.`Agent_ticket_data`", stmt, flags=re.I)
        s = re.sub(r"\[([a-zA-Z0-9_]+)\]", r"`\1`", s)
        s = re.sub(r"CAST\s*\(\s*N?'([^']+?)'\s*AS\s*DateTime2\s*\)", lambda m: f"'{m.group(1).replace('T', ' ')[:26]}'", s, flags=re.I)
        s = re.sub(r"CAST\s*\(\s*N?'([^']+?)'(?:\s*\+\d\d:\d\d)?\s*AS\s*DateTimeOffset\s*\)", lambda m: f"'{m.group(1).replace('T', ' ').split('+')[0][:26]}'", s, flags=re.I)
        s = re.sub(r"CAST\s*\(\s*([^()]+?)\s*AS\s*(?:Decimal|Numeric)(?:\([^)]*\))?\s*\)", r"\1", s, flags=re.I)
        s = re.sub(r"CAST\s*\(\s*N?'([^']+?)'\s*AS\s*Date\s*\)", r"'\1'", s, flags=re.I)
        s = re.sub(r"N'((?:''|[^'])*)'", r"'\1'", s)
        return s.rstrip(";") + ";"

    converted = [transform_sql(l) for l in lines]

    out_sql = BASE_DIR / "airline_agent_mysql.sql"
    final_content = (
        "-- ==========================================================================\n"
        "-- Airline_Agent Database & Table for MySQL / TiDB (Full 95 columns)\n"
        "-- ==========================================================================\n"
        + create_table_sql
        + "\nSET FOREIGN_KEY_CHECKS = 0;\n\n"
        + "-- Agent ticket data initial inserts\n"
        + "\n".join(converted)
        + "\n\nSET FOREIGN_KEY_CHECKS = 1;\n"
    )

    with open(out_sql, "w", encoding="utf-8") as f:
        f.write(final_content)

    print(f"Successfully generated {out_sql} with {len(col_matches)} columns and {len(converted)} insert statements!")

if __name__ == "__main__":
    main()
