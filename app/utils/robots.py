"""robots.txt compliance check, cached per domain for the lifetime of the process."""

import threading
import urllib.robotparser
from urllib.parse import urlparse

_lock = threading.Lock()
_parsers: dict[str, urllib.robotparser.RobotFileParser] = {}


def _get_parser(domain: str) -> urllib.robotparser.RobotFileParser:
    with _lock:
        parser = _parsers.get(domain)
        if parser is not None:
            return parser

        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(f"https://{domain}/robots.txt")
        try:
            parser.read()
        except Exception:
            # If robots.txt can't be fetched/parsed, err on the side of caution
            # and treat the site as disallowing automated access.
            parser = None
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
