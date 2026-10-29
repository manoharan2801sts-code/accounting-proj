"""
Creates the Agent's database and ticket table (AGENT_DB_NAME / AGENT_DB_TABLE
in .env, default Airline_Agent.dbo.Agent_ticket_data) - see
accounting/agent_db_scheduler.py. Safe to run again: existing ones are kept.

    python manage.py setup_agent_db               # create them
    python manage.py setup_agent_db --print-sql   # only show the SQL
"""
from django.core.management.base import BaseCommand
from django.db import connection, connections

from accounting import agent_db_scheduler


class Command(BaseCommand):
    help = "Creates the Agent database and its ticket table for the Automated Database Scheduler."

    def add_arguments(self, parser):
        parser.add_argument("--print-sql", action="store_true", help="Print the SQL instead of running it.")

    def handle(self, *args, print_sql=False, **options):
        db, table = agent_db_scheduler.table_names()
        sql = agent_db_scheduler.create_sql(db, table)
        if print_sql:
            self.stdout.write(sql)
            return
        if connection.vendor == "microsoft":
            with connection.cursor() as cursor:
                cursor.execute(f"IF DB_ID('{db}') IS NULL CREATE DATABASE [{db}];")
            batches = [b.strip() for b in sql.split("\nGO\n") if b.strip()]
            with connections[agent_db_scheduler.ALIAS].cursor() as cursor:
                for batch in batches:
                    if batch.startswith(("IF DB_ID", "USE ")):
                        continue   # done above / the agent_db connection is already on that database
                    cursor.execute(batch)
            connections[agent_db_scheduler.ALIAS].close()
        else:
            with connection.cursor() as cursor:
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db}`;")
            # Run schema creation on agent_db
            cols_def = []
            for c in agent_db_scheduler.HEADER_COLUMNS + agent_db_scheduler.PAX_COLUMNS:
                cols_def.append(f"`{c}` varchar({agent_db_scheduler.TEXT_SIZES.get(c, 100)}) DEFAULT NULL")
            for c in agent_db_scheduler.AMOUNT_COLUMNS:
                cols_def.append(f"`{c}` decimal(18,2) DEFAULT NULL")
            create_tbl = f"""CREATE TABLE IF NOT EXISTS `{db}`.`{table}` (
                `agent_row_id` bigint NOT NULL AUTO_INCREMENT PRIMARY KEY,
                `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                `company_id` int NOT NULL,
                {', '.join(cols_def)},
                KEY `ix_{table}_invoice` (`company_id`, `booking_status`, `booking_reference`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"""
            with connections[agent_db_scheduler.ALIAS].cursor() as cursor:
                cursor.execute(create_tbl)
            connections[agent_db_scheduler.ALIAS].close()
        self.stdout.write(self.style.SUCCESS(f"Ready: [{db}].[{table}]"))
