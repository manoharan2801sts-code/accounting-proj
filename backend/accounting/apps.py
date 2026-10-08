from django.apps import AppConfig


class AccountingConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "accounting"

    def ready(self):
        # Load the MySQL stand-in for the stored procedures at startup, so its
        # per-request cache is listening before the first request arrives
        # (the URLconf/views otherwise only import it during that request).
        from . import sp_mysql  # noqa: F401
