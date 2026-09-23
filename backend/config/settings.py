"""
Voyager ERP — Django settings (config file)
-----------------------------------------------------------------
Reads everything from .env via python-decouple, so credentials never
sit hardcoded in this file. Supports local MySQL and TiDB Cloud (SSL).
"""
import os
from pathlib import Path
import certifi
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR.parent

SECRET_KEY = config("DJANGO_SECRET_KEY", default="django-insecure-voyager-accounting-key-change-in-prod")
DEBUG = config("DJANGO_DEBUG", default=False, cast=bool)

# Render provides RENDER_EXTERNAL_HOSTNAME automatically
allowed_hosts_default = "localhost,127.0.0.1,.onrender.com"
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", default=allowed_hosts_default, cast=Csv())
render_hostname = config("RENDER_EXTERNAL_HOSTNAME", default=None)
if render_hostname and render_hostname not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_hostname)

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "corsheaders",
    "accounting",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"

# CORS configuration
CORS_ALLOWED_ORIGINS = [
    config("CORS_ALLOWED_ORIGIN", default="http://localhost:8080"),
    "http://127.0.0.1:8080",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]
if render_hostname:
    CORS_ALLOWED_ORIGINS.append(f"https://{render_hostname}")

# If DEBUG or running unified on Render, allow all origins or same-origin
if DEBUG or config("CORS_ALLOW_ALL", default=True, cast=bool):
    CORS_ALLOW_ALL_ORIGINS = True


# ---------------------------------------------------------------------------
# Database — MySQL / TiDB Cloud Serverless via PyMySQL
# ---------------------------------------------------------------------------
database_url = config("DATABASE_URL", default=config("TIDB_URL", default=""))

if database_url:
    from urllib.parse import urlparse, unquote
    parsed_db = urlparse(database_url)
    DB_USER = unquote(parsed_db.username) if parsed_db.username else "root"
    DB_PASSWORD = unquote(parsed_db.password) if parsed_db.password else ""
    DB_HOST = parsed_db.hostname or "127.0.0.1"
    DB_PORT = parsed_db.port or 4000
    db_path = parsed_db.path.lstrip("/").split("?")[0] if parsed_db.path else ""
    DB_NAME = db_path if db_path else "accounting_dep_db"
    has_ssl_query = "ssl" in parsed_db.query.lower()
else:
    DB_PORT = config("DB_PORT", default="3306")
    DB_HOST = config("DB_HOST", default="127.0.0.1")
    DB_NAME = config("DB_NAME", default="accounting_dep_db")
    DB_USER = config("DB_USER", default="root")
    DB_PASSWORD = config("DB_PASSWORD", default="")
    has_ssl_query = False

# TiDB Cloud Serverless requires SSL (port 4000 or host containing tidbcloud.com)
DB_SSL = (
    config("DB_SSL", default=False, cast=bool)
    or str(DB_PORT) == "4000"
    or ("tidbcloud.com" in DB_HOST.lower())
    or has_ssl_query
)

db_options = {
    "charset": "utf8mb4",
    "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
}
if DB_SSL:
    db_options["ssl"] = {"ca": certifi.where()}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": DB_NAME,
        "HOST": DB_HOST,
        "PORT": DB_PORT,
        "USER": DB_USER,
        "PASSWORD": DB_PASSWORD,
        "OPTIONS": db_options,
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

# ---------------------------------------------------------------------------
# Static files & Frontend assets (WhiteNoise)
# ---------------------------------------------------------------------------
STATIC_URL = "/assets/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [
    PROJECT_DIR / "assets",
]

# Django 5.0+ STORAGES configuration
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

USE_TZ = True
TIME_ZONE = "Asia/Kolkata"