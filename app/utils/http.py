"""Shared HTTP plumbing for scraper adapters: retries, timeouts, and a
per-domain rate limiter, all in one place so adapters stay small.
"""

import threading
import time
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Statuses that represent a transient failure worth retrying. 403 is
# deliberately excluded: it usually means an access-control/bot-management
# decision (e.g. Croma's Akamai WAF), and retrying would just hammer a site
# that has already said no.
RETRYABLE_STATUSES = (429, 500, 502, 503, 504)


class DomainRateLimiter:
    """Enforces a minimum delay between requests to the same domain."""

    def __init__(self, min_interval_seconds: float):
        self.min_interval_seconds = min_interval_seconds
        self._last_request_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, domain: str) -> None:
        with self._lock:
            last = self._last_request_at.get(domain)
            now = time.monotonic()
            if last is not None:
                elapsed = now - last
                remaining = self.min_interval_seconds - elapsed
                if remaining > 0:
                    time.sleep(remaining)
            self._last_request_at[domain] = time.monotonic()


def build_session(max_retries: int = 3, user_agent: str = DEFAULT_USER_AGENT) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=max_retries,
        backoff_factor=0.5,
        status_forcelist=RETRYABLE_STATUSES,
        allowed_methods=("GET", "HEAD"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept-Language": "en-IN,en;q=0.9",
            "Accept": "text/html,application/json,application/xhtml+xml,*/*;q=0.8",
        }
    )
    return session


@dataclass
class FetchResult:
    ok: bool
    status_code: int | None
    text: str | None
    url: str
    error: str | None = None
    blocked: bool = False
    elapsed_ms: float = 0.0


def fetch(
    session: requests.Session,
    url: str,
    *,
    timeout: float,
    rate_limiter: DomainRateLimiter | None = None,
    domain: str | None = None,
    params: dict | None = None,
    headers: dict | None = None,
) -> FetchResult:
    """GET a URL, never raising - failures are reported in FetchResult."""

    if rate_limiter is not None and domain is not None:
        rate_limiter.wait(domain)

    start = time.monotonic()
    try:
        response = session.get(url, timeout=timeout, params=params, headers=headers)
    except requests.RequestException as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        return FetchResult(ok=False, status_code=None, text=None, url=url, error=str(exc), elapsed_ms=elapsed_ms)

    elapsed_ms = (time.monotonic() - start) * 1000

    if response.status_code == 403:
        return FetchResult(
            ok=False,
            status_code=403,
            text=None,
            url=url,
            error="Blocked by source (403 - access control / bot protection)",
            blocked=True,
            elapsed_ms=elapsed_ms,
        )

    if not response.ok:
        return FetchResult(
            ok=False,
            status_code=response.status_code,
            text=None,
            url=url,
            error=f"HTTP {response.status_code}",
            elapsed_ms=elapsed_ms,
        )

    return FetchResult(ok=True, status_code=response.status_code, text=response.text, url=url, elapsed_ms=elapsed_ms)
