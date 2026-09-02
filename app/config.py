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

    EMI_DEFAULT_TENURE_MONTHS = _int("EMI_DEFAULT_TENURE_MONTHS", 12)
    EMI_DEFAULT_ANNUAL_RATE_PERCENT = _float("EMI_DEFAULT_ANNUAL_RATE_PERCENT", 14.0)

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SEARCH_CACHE_TTL_SECONDS = 0
