"""
In-process background daemon scheduler for Voyager ERP.
Automatically runs on Render / production inside Gunicorn:
  1. Automated Database Scheduler (agent_db_scheduler.run_once) - every 5 minutes
  2. Ticket Import Scheduler (ticket_import.process_pending) - every 5 minutes
Provides an on-demand trigger function and API view.
"""
import logging
import sys
import threading
import time
from datetime import datetime

from django.conf import settings
from django.db import connection, connections

logger = logging.getLogger(__name__)

_SCHEDULER_THREAD = None
_STARTED = False
_LOCK = threading.Lock()


def run_schedulers_now():
    """Executes one pass of both schedulers immediately and returns summary."""
    from accounting import agent_db_scheduler, ticket_import
    results = {}
    try:
        if getattr(settings, "AGENT_DB_SCHEDULER_ENABLED", True):
            results["agent_db"] = agent_db_scheduler.run_once()
        else:
            results["agent_db"] = {"status": "disabled"}
    except Exception as e:
        logger.exception("Background agent_db_scheduler pass failed")
        results["agent_db"] = {"error": str(e)}
    finally:
        try:
            connection.close()
            if agent_db_scheduler.ALIAS in connections:
                connections[agent_db_scheduler.ALIAS].close()
        except Exception:
            pass

    try:
        results["ticket_import"] = ticket_import.process_pending()
    except Exception as e:
        logger.exception("Background ticket_import pass failed")
        results["ticket_import"] = {"error": str(e)}
    finally:
        try:
            connection.close()
        except Exception:
            pass

    return results


def _scheduler_worker():
    interval_minutes = getattr(settings, "AGENT_DB_SCHEDULER_MINUTES", 5) or 5
    interval_seconds = max(60, interval_minutes * 60)
    logger.info("Voyager background scheduler started (interval: %dm)", interval_minutes)
    # Initial sleep to allow gunicorn workers to fully initialize and complete startup
    time.sleep(15)

    while True:
        try:
            run_schedulers_now()
        except Exception as e:
            logger.exception("Unexpected error in background scheduler loop: %s", e)
        time.sleep(interval_seconds)


def start_background_scheduler():
    """Starts the daemon thread if not already running and not in a management command."""
    global _STARTED, _SCHEDULER_THREAD
    with _LOCK:
        if _STARTED:
            return
        # Do not run during management commands like migrate, collectstatic, shell, etc.
        if len(sys.argv) > 1 and any(arg in sys.argv for arg in [
            "migrate", "collectstatic", "makemigrations", "check", "test",
            "setup_agent_db", "run_agent_db_scheduler", "run_ticket_import", "shell"
        ]):
            return

        _STARTED = True
        _SCHEDULER_THREAD = threading.Thread(
            target=_scheduler_worker,
            name="VoyagerBackgroundScheduler",
            daemon=True
        )
        _SCHEDULER_THREAD.start()
        logger.info("Voyager background scheduler daemon thread launched.")
