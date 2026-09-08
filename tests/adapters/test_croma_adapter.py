"""Croma is the source that turned out to be network/WAF-blocked from the
development environment (see app/scrapers/croma.py's module docstring for
the full story). The 403 tests below replay the *real* captured 403 response
body (tests/fixtures/croma_403.html - Akamai's "Access Denied" page) to prove
the adapter treats that as a clean, non-fatal partial failure rather than
raising and taking the whole /api/search request down with it.

`test_successful_listing_page_is_parsed_into_real_listings` replays a real
captured *successful* response (tests/fixtures/croma_listing.html, fetched
from an AWS ap-south-1/Mumbai host where Croma's WAF doesn't block the
request - see the README's "Deploying to AWS EC2" section) - the selectors
were previously unverified against live markup since no successful fetch had
been obtained. All confirmed accurate against this real page.
"""

import responses
from bs4 import BeautifulSoup

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


@responses.activate
def test_successful_listing_page_is_parsed_into_real_listings():
    responses.add(responses.GET, LISTING_URL, body=read_fixture("croma_listing.html"), status=200)

    adapter = CromaAdapter(ADAPTER_TEST_CONFIG)
    result = adapter.run(SearchQuery(model="iPhone"), crawl_id="test-crawl")

    assert result.ok is True
    assert result.blocked is False
    # The real page had 21 product cards, all genuine iPhone variants.
    assert len(result.listings) == 21
    assert all("iphone" in l.product_name_raw.lower() for l in result.listings)
    assert all(l.seller == "Croma" for l in result.listings)
    assert all(l.selling_price is not None for l in result.listings)

    by_name = {l.product_name_raw: l for l in result.listings}
    blue_15 = by_name["Apple iPhone 15 (128GB, Blue)"]
    assert blue_15.selling_price == 59900.0
    assert blue_15.mrp == 59900.0
    assert blue_15.product_url == "https://www.croma.com/apple-iphone-15-128gb-blue-/p/300684"

    # This card has a real discount (MRP != selling price) - confirms the
    # MRP selector fires correctly, not just the price one.
    discounted = by_name["Apple iPhone Air (256GB, Light Gold)"]
    assert discounted.mrp == 119900.0
    assert discounted.selling_price == 101900.0
    assert discounted.discount == 18000.0

    # Documented, real limitations of this page - not parsing bugs: the
    # product image is injected client-side (the static HTML has no <img>
    # tag at all in the card), and no bank/offer text is exposed at the
    # catalogue-card level (only price is here; offers live elsewhere).
    assert all(l.image_url is None for l in result.listings)
    assert all(l.offers == [] for l in result.listings)


@responses.activate
def test_listing_page_query_filters_by_model_text():
    responses.add(responses.GET, LISTING_URL, body=read_fixture("croma_listing.html"), status=200)

    adapter = CromaAdapter(ADAPTER_TEST_CONFIG)
    result = adapter.run(SearchQuery(model="iPhone 17 Pro Max"), crawl_id="test-crawl")

    assert result.ok is True
    assert len(result.listings) > 0
    assert all("17 pro max" in l.product_name_raw.lower() for l in result.listings)


def test_page_greater_than_one_returns_no_listings_without_fetching():
    # LISTING_URL is one fixed, unpaginated page - a page > 1 request must be
    # treated as "exhausted" immediately, with no network call at all.
    adapter = CromaAdapter(ADAPTER_TEST_CONFIG)
    result = adapter.run(SearchQuery(model="iPhone", page=2), crawl_id="test-crawl")

    assert result.ok is True
    assert result.listings == []


def test_offer_text_on_a_card_is_parsed_into_a_raw_offer():
    # None of the 21 real cards in croma_listing.html carry offer badges at
    # this catalogue-tile level (see test_successful_listing_page_is_parsed_
    # into_real_listings), so this exercises _parse_card's offer-text branch
    # directly against a minimal card shaped the way OFFER_SELECTORS expects,
    # in case Croma's markup adds this back for some other page/category.
    html = """
    <li class="product-item">
      <h3 class="product-title"><a href="/x/p/1">Apple iPhone 15 (128GB, Blue)</a></h3>
      <span class="amount">Rs.59,900</span>
      <div class="offer-text">10% instant discount with HDFC Bank</div>
    </li>
    """
    card = BeautifulSoup(html, "lxml").select_one("li.product-item")

    adapter = CromaAdapter(ADAPTER_TEST_CONFIG)
    listing = adapter._parse_card(card)

    assert len(listing.offers) == 1
    offer = listing.offers[0]
    assert "HDFC" in offer.offer_text
    assert offer.bank == "HDFC"
    assert offer.offer_type == "bank"
