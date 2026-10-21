from django.db import migrations, models


STRIP = """
IF EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = 'uq_voucher_company_no')
    ALTER TABLE dbo.Vouchers DROP CONSTRAINT uq_voucher_company_no;
-- PV-3 -> 3, JV21-2 -> 2 (the number after the last "-").
UPDATE dbo.Vouchers SET voucher_no = RIGHT(voucher_no, CHARINDEX('-', REVERSE(voucher_no)) - 1)
WHERE category = 'MANUAL' AND CHARINDEX('-', voucher_no) > 0;
"""
# Back: the old prefixes (category code + master type id) and the company-wide key.
RESTORE = """
IF EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = 'uq_voucher_company_series_no')
    ALTER TABLE dbo.Vouchers DROP CONSTRAINT uq_voucher_company_series_no;
UPDATE v SET voucher_no =
    CASE v.voucher_type WHEN 'Payment' THEN 'PV' WHEN 'Receipt' THEN 'RV' WHEN 'Contra' THEN 'CV'
                        WHEN 'Debit Note' THEN 'DN' WHEN 'Credit Note' THEN 'CN' ELSE 'JV' END
    + ISNULL(CAST(vt.id AS NVARCHAR(10)), '') + '-' + v.voucher_no
FROM dbo.Vouchers v
LEFT JOIN dbo.VoucherType vt ON vt.company_id = v.company_id AND vt.name = v.voucher_type_name
WHERE v.category = 'MANUAL' AND CHARINDEX('-', v.voucher_no) = 0;
ALTER TABLE dbo.Vouchers ADD CONSTRAINT uq_voucher_company_no UNIQUE (company_id, voucher_no);
"""


def strip_forward(apps, schema_editor):
    if schema_editor.connection.vendor == "microsoft":
        schema_editor.execute(STRIP)
    else:
        conn = schema_editor.connection
        with conn.cursor() as cur:
            try:
                cur.execute("ALTER TABLE `Vouchers` DROP INDEX `uq_voucher_company_no`;")
            except Exception:
                pass
            cur.execute("UPDATE `Vouchers` SET `voucher_no` = SUBSTRING_INDEX(`voucher_no`, '-', -1) WHERE `category` = 'MANUAL' AND `voucher_no` LIKE '%-%';")


def strip_backward(apps, schema_editor):
    if schema_editor.connection.vendor == "microsoft":
        schema_editor.execute(RESTORE)


class Migration(migrations.Migration):
    """Voucher-screen voucher numbers are plain 1, 2, 3 per series (no PV- / RV- / JV21- prefix)."""

    atomic = False
    dependencies = [("accounting", "0061_voucher_category_misc")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(strip_forward, strip_backward)],
            state_operations=[
                migrations.RemoveConstraint(model_name="voucher", name="uq_voucher_company_no"),
            ],
        ),
        migrations.AddConstraint(
            model_name="voucher",
            constraint=models.UniqueConstraint(fields=("company_id", "voucher_type", "voucher_type_name", "voucher_no"),
                                               name="uq_voucher_company_series_no"),
        ),
    ]
