#!/usr/bin/env python
"""
Voyager ERP — Django entry point.
This is what you run: `python manage.py runserver`
Django doesn't use a "main.py" — this file (manage.py) is the direct
equivalent: it's the script you always run commands through.
"""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Run: pip install -r requirements.txt"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
