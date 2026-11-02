from django.apps import AppConfig


class AccountingConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "accounting"

    def ready(self):
        # Load the MySQL stand-in for the stored procedures at startup, so its
        # per-request cache is listening before the first request arrives
        # (the URLconf/views otherwise only import it during that request).
        from . import sp_mysql  # noqa: F401
        import sys
        skip_cmds = ["load_initial_data", "migrate", "makemigrations", "collectstatic", "init_tidb"]
        if not any(cmd in " ".join(sys.argv) for cmd in skip_cmds):
            from . import background_scheduler
            background_scheduler.start_background_scheduler()
