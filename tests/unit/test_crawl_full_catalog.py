"""scripts/crawl_full_catalog.py calls a couple of adapter methods directly
by name (rather than going through adapter.search()/adapter.run()), so a
rename on the adapter side can silently break this script without any
adapter test catching it - exactly what happened when the Vijay Sales
category-filter method was renamed from _is_in_smartphones_category to
_is_in_mobiles_category (see app/scrapers/vijay_sales.py) and this script
was left calling the old name. This file exists to close that gap.
"""

import json

import pytest
import responses

from app.models import Listing
from app.scrapers.vijay_sales import GRAPHQL_URL, VijaySalesAdapter
from scripts.crawl_full_catalog import crawl_vijay_sales, run_full_catalog_crawl
from tests.adapters.conftest import ADAPTER_TEST_CONFIG

GRAPHQL_RESPONSE = {
    "data": {
        "products": {
            "total_count": 1,
            "page_info": {"current_page": 1, "total_pages": 1},
            "items": [
                {
                    "name": "Apple iPhone 15 (256GB Storage, Blue)",
                    "sku": "245001",
                    "url_key": "apple-iphone-15-256gb-storage-blue",
                    "stock_status": "IN_STOCK",
                    "rating_summary": 90,
                    "review_count": 5,
                    "categories": [
                        {"url_key": "mobiles-and-accessories"},
                        {"url_key": "mobiles"},
                        {"url_key": "iphones"},
                    ],
                    "small_image": {"url": "https://vsprod.vijaysales.com/media/i.jpg"},
                    "price_range": {
                        "minimum_price": {
                            "regular_price": {"value": 69900},
                            "final_price": {"value": 65900},
                            "discount": {"amount_off": 4000, "percent_off": 5.7},
                        }
                    },
                }
            ],
        }
    }
}


@pytest.fixture(autouse=True)
def _allow_all_robots(monkeypatch):
    # This script's tests are about crawl/persist wiring, not re-verifying
    # robots.txt compliance (already covered by tests/unit/test_robots.py) -
    # same reasoning as tests/adapters/conftest.py's fixture of the same name.
    monkeypatch.setattr("app.scrapers.base.robots.is_allowed", lambda url, user_agent: True)


@responses.activate
def test_crawl_vijay_sales_uses_the_current_category_filter_method():
    responses.add(responses.GET, GRAPHQL_URL, body=json.dumps(GRAPHQL_RESPONSE), status=200)

    adapter = VijaySalesAdapter(ADAPTER_TEST_CONFIG)
    listings = crawl_vijay_sales(adapter, crawl_id="test-crawl")

    assert len(listings) == 1
    assert listings[0].sku == "245001"


@responses.activate
def test_run_full_catalog_crawl_persists_listings_end_to_end(app):
    responses.add(responses.GET, GRAPHQL_URL, body=json.dumps(GRAPHQL_RESPONSE), status=200)

    summary = run_full_catalog_crawl(app, ["vijay_sales"], log=lambda *a, **k: None)

    assert summary["sources_succeeded"] == 1
    assert summary["total_persisted"] == 1
    assert Listing.query.count() == 1
