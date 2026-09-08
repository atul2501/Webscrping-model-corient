import os


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _normalize_database_url(url: str) -> str:
    # Render (like Heroku) hands out "postgres://..." connection strings,
    # but SQLAlchemy 1.4+/2.0 only recognizes "postgresql://" - without this,
    # a deploy fails immediately with NoSuchModuleError on first request.
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = _normalize_database_url(
        os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(os.getcwd(), "instance", "app.db"))
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    HTTP_TIMEOUT_SECONDS = _float("HTTP_TIMEOUT_SECONDS", 12)
    HTTP_MAX_RETRIES = _int("HTTP_MAX_RETRIES", 3)
    RATE_LIMIT_SECONDS_PER_DOMAIN = _float("RATE_LIMIT_SECONDS_PER_DOMAIN", 1.5)
    SEARCH_CACHE_TTL_SECONDS = _int("SEARCH_CACHE_TTL_SECONDS", 900)
    SCRAPE_MAX_WORKERS = _int("SCRAPE_MAX_WORKERS", 3)

    # Default size of one page of the *response* `results` array (distinct
    # from `page`/SearchQuery.page, which asks upstream sources with real
    # pagination - currently only Vijay Sales - for a deeper crawl). Set high
    # enough that a normal single-model search is never silently truncated;
    # a client can still request a smaller `result_page_size` explicitly to
    # exercise real pagination, capped at RESULTS_MAX_PAGE_SIZE.
    RESULTS_PAGE_SIZE = _int("RESULTS_PAGE_SIZE", 50)
    RESULTS_MAX_PAGE_SIZE = _int("RESULTS_MAX_PAGE_SIZE", 100)

    EMI_DEFAULT_TENURE_MONTHS = _int("EMI_DEFAULT_TENURE_MONTHS", 12)
    EMI_DEFAULT_ANNUAL_RATE_PERCENT = _float("EMI_DEFAULT_ANNUAL_RATE_PERCENT", 14.0)

    # scripts/scheduled_refresh.py's loop interval - a separate long-running
    # process (its own docker-compose service), not something started inside
    # the web app's gunicorn workers, so this never needs coordinating across
    # multiple workers.
    SCHEDULED_REFRESH_INTERVAL_SECONDS = _int("SCHEDULED_REFRESH_INTERVAL_SECONDS", 6 * 60 * 60)

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    # Unset (the default) means "log to stdout" - what Docker/Render want,
    # since Render's own log viewer reads container stdout and a file
    # written inside that ephemeral container would vanish on redeploy.
    # .env.example sets this for local dev, where a file is more useful.
    LOG_FILE = os.environ.get("LOG_FILE") or None


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SEARCH_CACHE_TTL_SECONDS = 0
    LOG_FILE = None  # tests should never write a log file to the repo
