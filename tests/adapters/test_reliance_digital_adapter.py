import responses

from app.scrapers.base import SearchQuery
from app.scrapers.reliance_digital import (
    BASE_URL,
    GENERIC_LISTING_URL,
    RelianceDigitalAdapter,
    _candidate_urls,
)
from tests.adapters.conftest import ADAPTER_TEST_CONFIG
from tests.conftest import read_fixture

APPLE_FALLBACK_URL = f"{BASE_URL}/collection/apple-smartphones"
SAMSUNG_FALLBACK_URL = f"{BASE_URL}/collection/samsung-smartphones"
IPHONE_17_PRO_URL = f"{BASE_URL}/collection/iphone-17-pro"


def test_candidate_urls_tries_the_specific_model_collection_first():
    urls = _candidate_urls("iPhone 17 Pro")
    assert urls[0] == IPHONE_17_PRO_URL
    assert urls[-1] == GENERIC_LISTING_URL


def test_candidate_urls_falls_back_to_apple_collection_for_unmapped_iphone():
    # "iPhone 16" has no curated model-specific slug (verified stale at
    # build time), but is still an Apple query - it should try the broader
    # Apple collection before the fully generic all-brands page.
    urls = _candidate_urls("iPhone 16")
    assert urls == [APPLE_FALLBACK_URL, GENERIC_LISTING_URL]


def test_candidate_urls_falls_back_to_brand_collection_for_other_known_brands():
    assert _candidate_urls("Samsung Galaxy S24") == [SAMSUNG_FALLBACK_URL, GENERIC_LISTING_URL]


def test_candidate_urls_unmapped_brand_only_tries_generic_page():
    # No curated slug exists for Nokia - must not guess one, just go
    # straight to the generic page.
    assert _candidate_urls("Nokia 3210") == [GENERIC_LISTING_URL]


@responses.activate
def test_parses_real_listing_fixture_into_matched_listings():
    # "Realme" has no Apple/model-specific slug, so it goes straight to the
    # generic page - keeps this test focused on parsing, not the cascade.
    responses.add(responses.GET, GENERIC_LISTING_URL, body=read_fixture("reliance_listing.html"), status=200)

    adapter = RelianceDigitalAdapter(ADAPTER_TEST_CONFIG)
    result = adapter.run(SearchQuery(model="Realme"), crawl_id="test-crawl")

    assert result.ok is True
    assert result.blocked is False
    assert len(result.listings) > 0
    assert all("realme" in l.product_name_raw.lower() for l in result.listings)
    assert any(l.selling_price is not None for l in result.listings)


@responses.activate
def test_out_of_stock_card_is_flagged_not_dropped():
    responses.add(responses.GET, GENERIC_LISTING_URL, body=read_fixture("reliance_listing.html"), status=200)

    adapter = RelianceDigitalAdapter(ADAPTER_TEST_CONFIG)
    result = adapter.run(SearchQuery(model="Realme"), crawl_id="test-crawl")

    assert result.ok is True
    matched = [l for l in result.listings if "realme" in l.product_name_raw.lower()]
    assert any(l.availability == "out_of_stock" for l in matched)


@responses.activate
def test_generic_page_error_is_handled_gracefully_not_raised():
    responses.add(responses.GET, GENERIC_LISTING_URL, status=500)

    adapter = RelianceDigitalAdapter(ADAPTER_TEST_CONFIG)
    result = adapter.run(SearchQuery(model="Realme"), crawl_id="test-crawl")

    assert result.ok is False
    assert result.listings == []


@responses.activate
def test_stale_model_specific_slug_falls_through_to_generic_page():
    # Simulates exactly what was observed for real during development: a
    # curated per-model collection slug that has since gone stale (404) -
    # the adapter must fall through to the Apple collection, then the
    # generic page, rather than treating the 404 as a hard failure.
    responses.add(responses.GET, IPHONE_17_PRO_URL, status=404)
    responses.add(responses.GET, APPLE_FALLBACK_URL, status=404)
    responses.add(responses.GET, GENERIC_LISTING_URL, body=read_fixture("reliance_listing.html"), status=200)

    adapter = RelianceDigitalAdapter(ADAPTER_TEST_CONFIG)
    result = adapter.run(SearchQuery(model="iPhone 17 Pro"), crawl_id="test-crawl")

    assert result.ok is True
    assert len(responses.calls) == 3


@responses.activate
def test_all_tiers_failing_reports_the_adapter_as_failed():
    responses.add(responses.GET, IPHONE_17_PRO_URL, status=500)
    responses.add(responses.GET, APPLE_FALLBACK_URL, status=500)
    responses.add(responses.GET, GENERIC_LISTING_URL, status=500)

    adapter = RelianceDigitalAdapter(ADAPTER_TEST_CONFIG)
    result = adapter.run(SearchQuery(model="iPhone 17 Pro"), crawl_id="test-crawl")

    assert result.ok is False
    assert result.listings == []
