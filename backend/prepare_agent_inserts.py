import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
AGENT_SCRIPT = Path(r"D:\MANOHARAN T\accounting soft backeps dep\2.11.26 morng live\Accounting Software Live\agent 2.11.26script.sql")

def main():
    with open(AGENT_SCRIPT, "r", encoding="utf-16") as f:
        text = f.read()

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
    
    # Save to airline_agent_mysql.sql with CREATE DATABASE and CREATE TABLE
    out_sql = BASE_DIR / "airline_agent_mysql.sql"
    with open(out_sql, "r", encoding="utf-8") as f:
        schema_part = f.read().split("INSERT INTO")[0].split("REPLACE INTO")[0].strip()

    final_content = schema_part + "\n\n-- Agent ticket data initial inserts\n"
    final_content += "\n".join(converted) + "\n"

    with open(out_sql, "w", encoding="utf-8") as f:
        f.write(final_content)

    print(f"Updated {out_sql} with {len(converted)} insert statements!")

if __name__ == "__main__":
    main()
