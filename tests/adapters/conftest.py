"""Adapter tests exercise HTML/JSON parsing against saved fixtures via the
`responses` library, which only intercepts calls the tests explicitly
register a URL for. The robots.txt pre-check in BaseAdapter.get() would
otherwise make a real network call (a fetch these tests never registered)
in every adapter test. These tests are about parsing/resilience logic, not
re-verifying robots.txt compliance (that's a one-time, documented design
decision - see app/utils/robots.py), so it's stubbed out here.
"""

import pytest

from app.utils import robots

# BaseAdapter reads settings via dict-style access (config["KEY"]) to match
# Flask's real app.config, which is dict-like, not attribute-like.
ADAPTER_TEST_CONFIG = {
    "HTTP_MAX_RETRIES": 1,
    "HTTP_TIMEOUT_SECONDS": 5,
    "RATE_LIMIT_SECONDS_PER_DOMAIN": 0,
}


@pytest.fixture(autouse=True)
def _allow_all_robots(monkeypatch):
    monkeypatch.setattr(robots, "is_allowed", lambda url, user_agent: True)
