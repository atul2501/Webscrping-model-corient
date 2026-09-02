"""Croma is the source that turned out to be network/WAF-blocked from the
development environment (see app/scrapers/croma.py's module docstring for
the full story). This test replays the *real* captured 403 response body
(tests/fixtures/croma_403.html - Akamai's "Access Denied" page) to prove the
adapter treats that as a clean, non-fatal partial failure rather than
raising and taking the whole /api/search request down with it.
"""

import responses

from tests.adapters.conftest import ADAPTER_TEST_CONFIG
from app.scrapers.base import SearchQuery
from app.scrapers.croma import LISTING_URL, CromaAdapter
from tests.conftest import read_fixture


@responses.activate
def test_403_from_source_is_reported_as_blocked_not_raised():
    responses.add(responses.GET, LISTING_URL, body=read_fixture("croma_403.html"), status=403)

    adapter = CromaAdapter(ADAPTER_TEST_CONFIG)
    result = adapter.run(SearchQuery(model="iPhone 17 Pro"), crawl_id="test-crawl")

    assert result.ok is False
    assert result.blocked is True
    assert result.listings == []
    assert result.error is not None


@responses.activate
def test_403_is_not_retried():
    responses.add(responses.GET, LISTING_URL, body=read_fixture("croma_403.html"), status=403)

    adapter = CromaAdapter(ADAPTER_TEST_CONFIG)
    adapter.run(SearchQuery(model="iPhone 17 Pro"), crawl_id="test-crawl")

    # urllib3's Retry only intercepts the configured status_forcelist (429/5xx);
    # 403 must fall straight through as a single attempt.
    assert len(responses.calls) == 1
