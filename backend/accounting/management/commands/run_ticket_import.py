"""
Ticket import scheduler - saves staged Auto Push airline tickets
(dbo.Ticket_Import_Staging) into the main tables, see ticket_import.py.

    python manage.py run_ticket_import                 # one run, then exit (Windows Task Scheduler)
    python manage.py run_ticket_import --interval 300  # keep running, every 5 minutes (start.bat)
"""
import time
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import connection

from accounting import ticket_import


class Command(BaseCommand):
    help = "Imports staged Auto Push airline tickets into Booking / Reschedule / Cancellation."

    def add_arguments(self, parser):
        parser.add_argument("--company", type=int, default=None, help="Only this company_id (default: all).")
        parser.add_argument("--batch-size", type=int, default=50, help="Documents claimed per pass.")
        parser.add_argument("--interval", type=int, default=0, help="Seconds between runs; 0 = run once and exit.")

    def handle(self, *args, company=None, batch_size=50, interval=0, **options):
        while True:
            stamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            try:
                result = ticket_import.process_pending(company, batch_size=batch_size)
                self.stdout.write(
                    f"[{stamp}] run {result['run_id']}: {result['imported']} imported, {result['failed']} failed"
                    + (f", {result['stuck_rows_reset']} stuck rows reset" if result["stuck_rows_reset"] else "")
                )
                for doc in result["documents"]:
                    detail = doc.get("invoice_number") or doc.get("error") or ""
                    self.stdout.write(f"    {doc['ticket_status']:<11} {doc['doc_ref']:<25} {doc['process_status']:<8} {detail}")
            except Exception as err:  # noqa: BLE001 - keep the scheduler alive; the next run retries
                self.stderr.write(f"[{stamp}] import run failed: {err}")
            finally:
                connection.close()   # a fresh DB connection every run - a long-lived one can go stale
            if not interval:
                break
            time.sleep(interval)
