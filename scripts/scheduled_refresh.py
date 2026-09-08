"""Runs the full-catalogue crawl (scripts/crawl_full_catalog.py) on a
repeating interval, forever - the spec's "Scheduled refresh / background
jobs" feature, "another approach" than Celery/RQ.

Deliberately its own standalone, long-running process rather than a job
scheduled from inside the Flask app's gunicorn workers: gunicorn runs
multiple worker processes (see docker-entrypoint.sh's `--workers 2`), and an
in-process scheduler (e.g. APScheduler started from the app factory) would
fire once per worker unless coordinated with a lock - a real source of
duplicate crawls that's easy to ship by accident. A separate process sidesteps
that entirely: exactly one of these runs, independent of how many web workers
exist, and it shares nothing with them except the same database.

Usage:
    python scripts/scheduled_refresh.py
    python scripts/scheduled_refresh.py --sources vijay_sales,reliance_digital
    SCHEDULED_REFRESH_INTERVAL_SECONDS=3600 python scripts/scheduled_refresh.py

In Docker, this runs as its own `scheduler` service in docker-compose.yml -
see the README's "Full-catalogue crawl (scheduled refresh)" section.
"""

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from scripts.crawl_full_catalog import CRAWLERS, run_full_catalog_crawl

logger = logging.getLogger("scheduled_refresh")


def run_forever(app, requested: list[str], interval_seconds: int, max_iterations: int | None = None) -> None:
    """The loop itself, factored out so tests can bound it with
    `max_iterations` instead of actually running forever. One failed
    iteration is logged and swallowed, never crashes the loop - the whole
    point of a background refresh is that a bad cycle (a source outage, a
    transient DB error) shouldn't take down future scheduled runs, the same
    "one failure doesn't sink everything" principle every adapter follows.
    """
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        with app.app_context():
            try:
                summary = run_full_catalog_crawl(app, requested, log=logger.info)
                logger.info("scheduled refresh cycle complete: %s", summary)
            except Exception:  # noqa: BLE001 - one bad cycle must not kill the scheduler
                logger.exception("scheduled refresh cycle failed unexpectedly")

        iterations += 1
        if max_iterations is None or iterations < max_iterations:
            time.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the full-catalogue crawl on a repeating interval.")
    parser.add_argument("--sources", default=",".join(CRAWLERS.keys()), help="Comma-separated source names")
    args = parser.parse_args()
    requested = [s.strip() for s in args.sources.split(",") if s.strip()]

    app = create_app()
    logging.basicConfig(level=app.config["LOG_LEVEL"])
    interval = app.config["SCHEDULED_REFRESH_INTERVAL_SECONDS"]
    logger.info("starting scheduled refresh: sources=%s interval=%ss", requested, interval)
    run_forever(app, requested, interval)


if __name__ == "__main__":
    main()
