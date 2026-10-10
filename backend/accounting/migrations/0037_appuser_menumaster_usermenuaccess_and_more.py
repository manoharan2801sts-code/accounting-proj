# Migration 0037: AppUser, MenuMaster, UserMenuAccess models + Cancellation line TDS overrides
# Safe for TiDB Cloud Serverless and MySQL (idempotent, guarded, separates DDL)

import django.db.models.deletion
from django.db import migrations, models


def _tables(cursor, conn):
    return {t.lower(): t for t in conn.introspection.table_names(cursor)}


def _columns(cursor, conn, table):
    return {c.name.lower() for c in conn.introspection.get_table_description(cursor, table)}


def forwards(apps, schema_editor):
    conn = schema_editor.connection
    q = schema_editor.quote_name
    with conn.cursor() as cursor:
        tables = _tables(cursor, conn)

        # 1. Add TDS override fields to Cancellation_Al_TicketLines if not present
        if "cancellation_al_ticketlines" in tables:
            actual_table = tables["cancellation_al_ticketlines"]
            cols = _columns(cursor, conn, actual_table)
            if "tds_amount_override" not in cols:
                cursor.execute(f"ALTER TABLE {q(actual_table)} ADD COLUMN `tds_amount_override` decimal(14,2) NULL")
            if "supp_tds_amount_override" not in cols:
                cursor.execute(f"ALTER TABLE {q(actual_table)} ADD COLUMN `supp_tds_amount_override` decimal(14,2) NULL")

        # 2. Create AppUsers table if not exists
        if "appusers" not in tables:
            cursor.execute("""
                CREATE TABLE `AppUsers` (
                    `id` INT AUTO_INCREMENT PRIMARY KEY,
                    `full_name` VARCHAR(150) NOT NULL,
                    `email` VARCHAR(200) NOT NULL,
                    `role` VARCHAR(50) NOT NULL DEFAULT 'User',
                    `branch_name` VARCHAR(100) NULL,
                    `password_hash` VARCHAR(256) NULL,
                    `is_super_admin` TINYINT(1) NOT NULL DEFAULT 0,
                    `is_active` TINYINT(1) NOT NULL DEFAULT 1,
                    `created_at` DATETIME(6) NOT NULL,
                    `updated_at` DATETIME(6) NOT NULL,
                    UNIQUE KEY `uq_app_user_email` (`email`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
        else:
            cols = _columns(cursor, conn, tables["appusers"])
            if "password_hash" not in cols:
                cursor.execute("ALTER TABLE `AppUsers` ADD COLUMN `password_hash` VARCHAR(256) NULL")

        # 3. Create MenuMaster table if not exists
        tables = _tables(cursor, conn)
        if "menumaster" not in tables:
            cursor.execute("""
                CREATE TABLE `MenuMaster` (
                    `id` INT AUTO_INCREMENT PRIMARY KEY,
                    `menu_key` VARCHAR(60) NOT NULL,
                    `title` VARCHAR(100) NOT NULL,
                    `parent_key` VARCHAR(60) NULL,
                    `module` VARCHAR(20) NOT NULL,
                    `sort_order` INT UNSIGNED NOT NULL DEFAULT 0,
                    `is_active` TINYINT(1) NOT NULL DEFAULT 1,
                    UNIQUE KEY `uq_menu_master_key` (`menu_key`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

        # 4. Create UserMenuAccess table if not exists
        tables = _tables(cursor, conn)
        if "usermenuaccess" not in tables:
            cursor.execute("""
                CREATE TABLE `UserMenuAccess` (
                    `id` INT AUTO_INCREMENT PRIMARY KEY,
                    `user_id` INT NOT NULL,
                    `menu_key` VARCHAR(60) NOT NULL,
                    `can_view` TINYINT(1) NOT NULL DEFAULT 0,
                    `can_add` TINYINT(1) NOT NULL DEFAULT 0,
                    `can_edit` TINYINT(1) NOT NULL DEFAULT 0,
                    `can_delete` TINYINT(1) NOT NULL DEFAULT 0,
                    `created_by_id` INT NULL,
                    `created_at` DATETIME(6) NOT NULL,
                    `updated_at` DATETIME(6) NOT NULL,
                    UNIQUE KEY `uq_user_menu_access` (`user_id`, `menu_key`),
                    KEY `UserMenuAcc_user_id_9d1265_idx` (`user_id`),
                    CONSTRAINT `fk_uma_user` FOREIGN KEY (`user_id`) REFERENCES `AppUsers` (`id`) ON DELETE CASCADE,
                    CONSTRAINT `fk_uma_menu` FOREIGN KEY (`menu_key`) REFERENCES `MenuMaster` (`menu_key`) ON DELETE CASCADE,
                    CONSTRAINT `fk_uma_creator` FOREIGN KEY (`created_by_id`) REFERENCES `AppUsers` (`id`) ON DELETE SET NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)

        # 5. Seed MenuMaster entries
        menus = [
            ("company-master", "Company Master", None, "Masters", 1, 1),
            ("groups", "Groups", None, "Masters", 2, 1),
            ("accounts", "Chart of Accounts", None, "Masters", 3, 1),
            ("voucher-type", "Voucher Type", None, "Masters", 4, 1),
            ("supplier-master", "Supplier Master", None, "Masters", 5, 1),
            ("master-mapping", "Ledger Mapping", None, "Masters", 6, 1),
            ("fop-master", "FOP Master", None, "Masters", 7, 1),
            ("pg-master", "PG Master", None, "Masters", 8, 1),
            ("tickets", "Airline Booking", None, "Transactions", 1, 1),
            ("trans-airline-reschedule", "Airline Re-issue", None, "Transactions", 2, 1),
            ("trans-airline-cancellation", "Airline Cancellation", None, "Transactions", 3, 1),
            ("vouchers", "Journal / Manual Vouchers", None, "Transactions", 4, 1),
            ("rep-day-book", "Day Book", None, "Reports", 1, 1),
            ("rep-cash-bank-book", "Cash & Bank Book", None, "Reports", 2, 1),
            ("rep-ledger-book", "Ledger Book", None, "Reports", 3, 1),
            ("rep-trial-balance", "Trial Balance", None, "Reports", 4, 1),
            ("rep-profit-loss", "Profit & Loss", None, "Reports", 5, 1),
            ("rep-balance-sheet", "Balance Sheet", None, "Reports", 6, 1),
            ("rep-dsr-airline", "DSR Airline Booking", None, "Reports", 7, 1),
            ("user-management", "User Management", None, "Control Panel", 1, 0),
        ]
        for m_key, title, parent_key, module, sort_order, is_active in menus:
            cursor.execute("""
                INSERT INTO `MenuMaster` (`menu_key`, `title`, `parent_key`, `module`, `sort_order`, `is_active`)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE `title` = VALUES(`title`), `parent_key` = VALUES(`parent_key`),
                                        `module` = VALUES(`module`), `sort_order` = VALUES(`sort_order`),
                                        `is_active` = VALUES(`is_active`)
            """, [m_key, title, parent_key, module, sort_order, is_active])

        # 6. Seed Super Admin user if not exists
        pwd_hash = "pbkdf2_sha256$1000000$8CjKrdQgM6iC0yu8H2qAmz$wqNUeEqhrNNodeIkmzHuwyOOaFK3E6ZfNPAGOt8F0EE="
        initial_users = [
            ("Ananya Krishnan", "ananya.krishnan@travelagency.com", "Administrator", "Delhi HQ", 1, 1, pwd_hash),
            ("Administrator", "admin@travelagency.com", "Super Admin", "Delhi HQ", 1, 1, pwd_hash),
        ]
        for name, email, role, branch, is_sa, is_act, phash in initial_users:
            cursor.execute("""
                INSERT INTO `AppUsers` (`full_name`, `email`, `role`, `branch_name`, `is_super_admin`, `is_active`, `password_hash`, `created_at`, `updated_at`)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON DUPLICATE KEY UPDATE `is_super_admin` = 1, `is_active` = 1,
                                        `password_hash` = COALESCE(`password_hash`, VALUES(`password_hash`))
            """, [name, email, role, branch, is_sa, is_act, phash])


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0036_cancellation_tables_renames_rescheduled_flags"),
    ]

    operations = [
        migrations.CreateModel(
            name="AppUser",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("full_name", models.CharField(max_length=150)),
                ("email", models.EmailField(max_length=200)),
                ("role", models.CharField(default="User", max_length=50)),
                ("branch_name", models.CharField(blank=True, max_length=100, null=True)),
                ("password_hash", models.CharField(blank=True, max_length=256, null=True)),
                ("is_super_admin", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "AppUsers",
            },
        ),
        migrations.CreateModel(
            name="MenuMaster",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("menu_key", models.CharField(max_length=60)),
                ("title", models.CharField(max_length=100)),
                ("parent_key", models.CharField(blank=True, max_length=60, null=True)),
                ("module", models.CharField(choices=[("Masters", "Masters"), ("Transactions", "Transactions"), ("Reports", "Reports"), ("Control Panel", "Control Panel")], max_length=20)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "db_table": "MenuMaster",
                "ordering": ["module", "sort_order"],
            },
        ),
        migrations.CreateModel(
            name="UserMenuAccess",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("can_view", models.BooleanField(default=False)),
                ("can_add", models.BooleanField(default=False)),
                ("can_edit", models.BooleanField(default=False)),
                ("can_delete", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, db_column="created_by_id", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="granted_accesses", to="accounting.appuser")),
                ("menu", models.ForeignKey(db_column="menu_key", on_delete=django.db.models.deletion.CASCADE, related_name="user_access", to="accounting.menumaster", to_field="menu_key")),
                ("user", models.ForeignKey(db_column="user_id", on_delete=django.db.models.deletion.CASCADE, related_name="menu_access", to="accounting.appuser")),
            ],
            options={
                "db_table": "UserMenuAccess",
            },
        ),
        migrations.AddField(
            model_name="cancellationairlineticketline",
            name="supp_tds_amount_override",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name="cancellationairlineticketline",
            name="tds_amount_override",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
        ),
        migrations.AddConstraint(
            model_name="appuser",
            constraint=models.UniqueConstraint(fields=("email",), name="uq_app_user_email"),
        ),
        migrations.AddConstraint(
            model_name="menumaster",
            constraint=models.UniqueConstraint(fields=("menu_key",), name="uq_menu_master_key"),
        ),
        migrations.AddIndex(
            model_name="usermenuaccess",
            index=models.Index(fields=["user"], name="UserMenuAcc_user_id_9d1265_idx"),
        ),
        migrations.AddConstraint(
            model_name="usermenuaccess",
            constraint=models.UniqueConstraint(fields=("user", "menu"), name="uq_user_menu_access"),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
