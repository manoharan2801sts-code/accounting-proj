from django.db import migrations, models


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `MasterMappingHistory` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `company_id` integer NOT NULL,
    `product_type` varchar(20) NOT NULL,
    `masters_category` varchar(40) NOT NULL,
    `field_name` varchar(60) NOT NULL,
    `ledger_id` integer NOT NULL,
    `ledger_name` varchar(200) NULL,
    `effective_from` date NOT NULL,
    `created_at` datetime(6) NOT NULL,
    `updated_at` datetime(6) NOT NULL,
    UNIQUE KEY `uq_master_mapping_history_effective_from` (`company_id`, `product_type`, `field_name`, `effective_from`),
    KEY `mmh_lookup_idx` (`company_id`, `product_type`, `field_name`, `effective_from`)
);
"""


def seed_history(apps, schema_editor):
    MasterMapping = apps.get_model("accounting", "MasterMapping")
    MasterMappingHistory = apps.get_model("accounting", "MasterMappingHistory")
    for m in MasterMapping.objects.all():
        if not MasterMappingHistory.objects.filter(
            company_id=m.company_id, product_type=m.product_type, field_name=m.field_name, effective_from=m.effective_from
        ).exists():
            MasterMappingHistory.objects.create(
                company_id=m.company_id,
                product_type=m.product_type,
                masters_category=m.masters_category,
                field_name=m.field_name,
                ledger_id=m.ledger_id,
                ledger_name=m.ledger_name,
                effective_from=m.effective_from,
            )


class Migration(migrations.Migration):
    """Ledger Mapping effective-date history (like PGMasterHistory), seeded from the current mappings."""

    dependencies = [("accounting", "0053_vouchertype_numbering_behaviour")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="MasterMappingHistory",
                    fields=[
                        ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("company_id", models.IntegerField()),
                        ("product_type", models.CharField(max_length=20)),
                        ("masters_category", models.CharField(max_length=40)),
                        ("field_name", models.CharField(max_length=60)),
                        ("ledger_id", models.IntegerField()),
                        ("ledger_name", models.CharField(blank=True, max_length=200, null=True)),
                        ("effective_from", models.DateField()),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                    ],
                    options={"db_table": "MasterMappingHistory"},
                ),
                migrations.AddConstraint(
                    model_name="mastermappinghistory",
                    constraint=models.UniqueConstraint(fields=("company_id", "product_type", "field_name", "effective_from"),
                                                       name="uq_master_mapping_history_effective_from"),
                ),
                migrations.AddIndex(
                    model_name="mastermappinghistory",
                    index=models.Index(fields=["company_id", "product_type", "field_name", "effective_from"], name="mmh_lookup_idx"),
                ),
            ],
            database_operations=[
                migrations.RunSQL(CREATE_TABLE_SQL, migrations.RunSQL.noop),
            ],
        ),
        migrations.RunPython(seed_history, migrations.RunPython.noop),
    ]
