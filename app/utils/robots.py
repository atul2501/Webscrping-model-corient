"""robots.txt compliance check, cached per domain for the lifetime of the process."""

import logging
import threading
import urllib.robotparser
from urllib.parse import urlparse

import requests

from app.utils.http import DEFAULT_USER_AGENT

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_parsers: dict[str, urllib.robotparser.RobotFileParser] = {}
FETCH_TIMEOUT_SECONDS = 10


def _fetch_parser(domain: str) -> urllib.robotparser.RobotFileParser | None:
    # RobotFileParser.read() does its own fetch via stdlib urllib, with
    # Python's default User-Agent ("Python-urllib/x.y") and no timeout - a
    # site's bot-management can reject or hang on exactly that signature
    # (seen live: this made a perfectly-allowed URL look "unreadable" and
    # get treated as disallowed - see is_allowed below). Fetching with our
    # own session (a real browser UA, a bounded timeout) and handing the
    # text to parse() instead of calling read() avoids depending on
    # urllib's own fetch/error behaviour for something this consequential.
    try:
        response = requests.get(
            f"https://{domain}/robots.txt",
            timeout=FETCH_TIMEOUT_SECONDS,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("failed to fetch robots.txt for %s: %s", domain, exc)
        return None

    parser = urllib.robotparser.RobotFileParser()
    parser.parse(response.text.splitlines())
    return parser


def _get_parser(domain: str) -> urllib.robotparser.RobotFileParser | None:
    with _lock:
        cached = _parsers.get(domain)
        if cached is not None:
            return cached

    # Fetched outside the lock - this is a network call, and it shouldn't
    # block other threads checking a different (or even the same) domain.
    # A duplicate in-flight fetch for the same domain is possible but
    # harmless (both just re-parse the same robots.txt).
    parser = _fetch_parser(domain)
    if parser is None:
        # Deliberately not cached: a transient failure (a cold-start DNS
        # blip, one dropped connection) must not permanently blacklist a
        # domain for the rest of this process's life the way caching `None`
        # here used to - the next call just retries the fetch. Only a
        # successful parse is stable enough to be worth caching.
        return None

    with _lock:
        _parsers[domain] = parser
    return parser


def is_allowed(url: str, user_agent: str) -> bool:
    """Return True only if robots.txt was readable and explicitly allows this path."""

    domain = urlparse(url).netloc
    parser = _get_parser(domain)
    if parser is None:
        return False
    try:
        return parser.can_fetch(user_agent, url)
    except Exception:
        return False
