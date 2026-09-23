#!/usr/bin/env python
"""
TiDB Cloud Migration & Initialization Script
-----------------------------------------------------------------
Initializes the database schema and seed data on TiDB Cloud Serverless (or local MySQL).
Executes Schema_mysql.sql with SSL verification and prints verification counts.

Usage:
    python init_tidb.py
    python init_tidb.py --url="mysql://user:pass@host:4000/db?ssl-mode=REQUIRED"
"""

import sys
import os
from pathlib import Path
from urllib.parse import urlparse, unquote
import certifi
import pymysql

# Set path to include backend
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Load settings/env via python-decouple if available
try:
    from decouple import config
except ImportError:
    def config(key, default=None, cast=None):
        val = os.environ.get(key, default)
        if cast and val is not None:
            return cast(val)
        return val


def get_connection_params():
    # 1. Check CLI arguments
    for arg in sys.argv[1:]:
        if arg.startswith("--url="):
            url = arg.split("=", 1)[1].strip('"\'')
            p = urlparse(url)
            return {
                "host": p.hostname or "127.0.0.1",
                "port": p.port or 4000,
                "user": unquote(p.username) if p.username else "root",
                "password": unquote(p.password) if p.password else "",
                "database": p.path.lstrip("/").split("?")[0] if p.path else "accounting_dep_db",
                "ssl": True,
            }

    # 2. Check DATABASE_URL or TIDB_URL in environment or .env
    db_url = config("DATABASE_URL", default=config("TIDB_URL", default=None))
    if db_url:
        p = urlparse(db_url)
        return {
            "host": p.hostname or "127.0.0.1",
            "port": p.port or 4000,
            "user": unquote(p.username) if p.username else "root",
            "password": unquote(p.password) if p.password else "",
            "database": p.path.lstrip("/").split("?")[0] if p.path else "accounting_dep_db",
            "ssl": True,
        }

    # 3. Check individual variables
    host = config("DB_HOST", default="127.0.0.1")
    port = int(config("DB_PORT", default=3306))
    user = config("DB_USER", default="root")
    password = config("DB_PASSWORD", default="")
    db_name = config("DB_NAME", default="accounting_dep_db")
    ssl = config("DB_SSL", default=False, cast=bool) or port == 4000 or "tidbcloud.com" in host.lower()

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "database": db_name,
        "ssl": ssl,
    }


def split_sql_statements(sql_text):
    """Splits SQL script into individual executable statements."""
    statements = []
    buffer = []
    for line in sql_text.splitlines():
        trimmed = line.strip()
        # Skip pure comment lines
        if trimmed.startswith("--") or trimmed.startswith("/*") or not trimmed:
            continue
        buffer.append(line)
        if trimmed.endswith(";"):
            statement = "\n".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
    if buffer:
        remaining = "\n".join(buffer).strip()
        if remaining:
            statements.append(remaining)
    return statements


def main():
    print("=" * 70)
    print("  Voyager ERP — TiDB Cloud Serverless Database Setup")
    print("=" * 70)

    params = get_connection_params()
    print(f"\nConnecting to database:")
    print(f"  Host:     {params['host']}")
    print(f"  Port:     {params['port']}")
    print(f"  User:     {params['user']}")
    print(f"  Database: {params['database']}")
    print(f"  SSL:      {'Enabled (certifi)' if params['ssl'] else 'Disabled'}")

    sql_file = BASE_DIR / "Schema_mysql.sql"
    if not sql_file.exists():
        print(f"\n[ERROR] Schema file not found at: {sql_file}")
        sys.exit(1)

    with open(sql_file, "r", encoding="utf-8") as f:
        sql_content = f.read()

    # If the user specified a custom database name, replace accounting_dep_db
    target_db = params["database"]
    if target_db and target_db != "accounting_dep_db":
        print(f"\nNote: Adapting schema script for database: '{target_db}'...")
        sql_content = sql_content.replace("`accounting_dep_db`", f"`{target_db}`")

    statements = split_sql_statements(sql_content)
    print(f"Parsed {len(statements)} SQL statements from Schema_mysql.sql")

    conn_args = {
        "host": params["host"],
        "port": params["port"],
        "user": params["user"],
        "password": params["password"],
        "charset": "utf8mb4",
        "autocommit": True,
    }
    if params["ssl"]:
        conn_args["ssl"] = {"ca": certifi.where()}

    try:
        # First connect without specifying database to allow CREATE DATABASE
        conn = pymysql.connect(**conn_args)
    except Exception as e:
        print(f"\n[ERROR] Failed to connect to database host: {e}")
        print("\nPlease check your credentials and make sure:")
        print("  1. The TiDB cluster is running.")
        print("  2. If using TiDB Cloud, SSL is required and host/user/password are correct.")
        sys.exit(1)

    print("\n[OK] Connected successfully! Executing database setup...")

    success_count = 0
    with conn.cursor() as cursor:
        for i, stmt in enumerate(statements, 1):
            try:
                cursor.execute(stmt)
                success_count += 1
            except Exception as e:
                # Ignore minor drop errors or non-critical warnings
                if "Unknown database" in str(e) or "doesn't exist" in str(e):
                    continue
                print(f"\n[WARNING] Statement {i} failed: {e}")
                print(f"SQL: {stmt[:120]}...")

    print(f"\n[OK] Executed {success_count} statements successfully!")

    # Verification queries
    print("\nVerifying database tables & seed data:")
    tables_to_check = [
        "CompanyMaster",
        "Ledger_Groups",
        "Ledgers",
        "MasterMapping",
        "FOPMaster",
        "PGMaster",
        "SupplierCommissionRules",
        "JournalVoucher",
        "Vouchers",
        "Tickets",
        "TicketLines",
        "django_migrations",
    ]

    with conn.cursor() as cursor:
        try:
            cursor.execute(f"USE `{target_db}`")
        except Exception:
            pass

        print("-" * 50)
        print(f"{'Table Name':<30} | {'Row Count':>10}")
        print("-" * 50)
        for tbl in tables_to_check:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM `{tbl}`")
                cnt = cursor.fetchone()[0]
                print(f"{tbl:<30} | {cnt:>10}")
            except Exception as e:
                print(f"{tbl:<30} | {'Not Found':>10}")
        print("-" * 50)

    conn.close()
    print("\n" + "=" * 70)
    print("  Database initialization completed successfully!")
    print("  You can now launch your application on Render.")
    print("=" * 70)


if __name__ == "__main__":
    main()
