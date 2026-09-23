# Multi-city sectors on ticket-entry.html's Passenger & Segment Details:
# Flight No and Travel Date moved OUT of the main passenger form and INTO
# a per-sector "Add Sector" popup (Sector From/To, Travel Date, Flight No,
# Cabin, Class, Fare Type) — one passenger line can now carry several
# sectors, stored comma-joined in the same order (sector "BOM-DXB,DXB-JFK",
# flight_no/cabin/travel_class/fare_type the same). travel_date changes
# from a real DateField to plain text for the same reason: multi-city
# segments can have different dates (comma-joined when they differ, a
# single value when they don't) — a DateField can't hold that.
# Run the ALTER TABLE in rough.txt by hand against Accounting_DB, then:
#   python manage.py migrate accounting --fake

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0008_ledger_remove_airline_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticketline',
            name='cabin',
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
        migrations.AddField(
            model_name='ticketline',
            name='fare_type',
            field=models.CharField(blank=True, max_length=300, null=True),
        ),
        migrations.AddField(
            model_name='ticketline',
            name='travel_class',
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
        migrations.AlterField(
            model_name='ticketline',
            name='flight_no',
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
        migrations.AlterField(
            model_name='ticketline',
            name='sector',
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
        migrations.AlterField(
            model_name='ticketline',
            name='travel_date',
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
    ]
