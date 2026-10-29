"""
Automated Database Scheduler - saves the tickets the Agent put in the
Airline_Agent database as invoices (accounting/agent_db_scheduler.py).

    python manage.py run_agent_db_scheduler            # every AGENT_DB_SCHEDULER_MINUTES (.env, default 5) - start.bat
    python manage.py run_agent_db_scheduler --once     # one run, then exit (Windows Task Scheduler)
    python manage.py run_agent_db_scheduler --minutes 1
"""
import time
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection, connections

from accounting import agent_db_scheduler


class Command(BaseCommand):
    help = "Imports the Agent database tickets (Airline_Agent) into Booking / Reschedule / Cancellation."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="One run, then exit.")
        parser.add_argument("--minutes", type=int, default=None,
                            help="Minutes between runs (default: AGENT_DB_SCHEDULER_MINUTES in .env).")

    def handle(self, *args, once=False, minutes=None, **options):
        if not settings.AGENT_DB_SCHEDULER_ENABLED:
            self.stdout.write("Automated Database Scheduler is off (AGENT_DB_SCHEDULER_ENABLED=False in .env).")
            return
        minutes = max(1, minutes or settings.AGENT_DB_SCHEDULER_MINUTES)
        db, table = agent_db_scheduler.table_names()
        self.stdout.write(f"Automated Database Scheduler: [{db}].dbo.[{table}] every {minutes} minute(s).")
        while True:
            stamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            try:
                result = agent_db_scheduler.run_once()
                if result["records_fetched"]:
                    self.stdout.write(f"[{stamp}] {result['records_fetched']} rows / {result['invoices_fetched']} invoices: "
                                      f"{result['message']}")
                    for d in result["documents"]:
                        self.stdout.write(f"    {d['booking_status'] or '-':<2} {d['booking_reference'] or '-':<15} "
                                          f"{d['status']:<9} {d['invoice_number'] or ''}")
                else:
                    self.stdout.write(f"[{stamp}] nothing new"
                                      + (f" ({result['refreshed']} waiting rows updated)" if result["refreshed"] else ""))
            except Exception as err:  # noqa: BLE001 - keep the scheduler alive; the next run tries again
                hint = " - run `python manage.py setup_agent_db` first" if "Cannot open database" in str(err) else ""
                self.stderr.write(f"[{stamp}] run failed: {err}{hint}")
            finally:
                connection.close()   # fresh connections every run - long-lived ones can go stale
                connections[agent_db_scheduler.ALIAS].close()
            if once:
                break
            time.sleep(minutes * 60)
