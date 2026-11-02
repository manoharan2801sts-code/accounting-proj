"""
Rebuilds the year-wise ledger tables [YY-YY-Accounting_Ledger] (Apr - Mar) from the
documents (accounting/ledger_months.py) - after data was changed outside the
app (SSMS, scripts). Saves in the app keep them current by themselves.

    python manage.py rebuild_accounting_ledger              # every company
    python manage.py rebuild_accounting_ledger --company 1
"""
from django.core.management.base import BaseCommand

from accounting import ledger_months, sp_client


class Command(BaseCommand):
    help = "Rebuilds the year-wise ledger tables [YY-YY-Accounting_Ledger]."

    def add_arguments(self, parser):
        parser.add_argument("--company", type=int, help="Only this company id.")

    def handle(self, *args, company=None, **options):
        companies = [company] if company else [c["id"] for c in sp_client.company_master_list()]
        for company_id in companies:
            ledger_months.rebuild(company_id)
            self.stdout.write(self.style.SUCCESS(f"Company {company_id}: ledger year tables rebuilt."))
