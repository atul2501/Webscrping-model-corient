import json

import responses

from tests.adapters.conftest import ADAPTER_TEST_CONFIG
from app.scrapers.base import SearchQuery
from app.scrapers.vijay_sales import BASE_URL, GRAPHQL_URL, VijaySalesAdapter
from tests.conftest import read_fixture

# A trimmed, representative slice of the real response captured live from
# https://www.vijaysales.com/api/graphql (products(search: "iphone 17")) -
# includes one genuine phone and one accessory to exercise the
# accessory-keyword filter.
GRAPHQL_RESPONSE = {
    "data": {
        "products": {
            "total_count": 2,
            "items": [
                {
                    "name": "Apple iPhone 17 (256GB Storage, Black) P245179",
                    "sku": "245179",
                    "url_key": "apple-iphone-17-256gb-storage-black",
                    "stock_status": "IN_STOCK",
                    "rating_summary": 97,
                    "review_count": 13,
                    "small_image": {"url": "https://vsprod.vijaysales.com/media/iphone17black.jpg"},
                    "price_range": {
                        "minimum_price": {
                            "regular_price": {"value": 82900},
                            "final_price": {"value": 79900},
                            "discount": {"amount_off": 3000, "percent_off": 3.6},
                        }
                    },
                },
                {
                    "name": "Apple iPhone 17 Silicone Case with MagSafe - Black",
                    "sku": "245389",
                    "url_key": "apple-iphone-17-silicone-case-with-magsafe-black",
                    "stock_status": "IN_STOCK",
                    "rating_summary": 0,
                    "review_count": 0,
                    "small_image": {"url": "https://vsprod.vijaysales.com/media/case.jpg"},
                    "price_range": {
                        "minimum_price": {
                            "regular_price": {"value": 3890},
                            "final_price": {"value": 3890},
                            "discount": {"amount_off": 0, "percent_off": 0},
                        }
                    },
                },
            ],
        }
    }
}


@responses.activate
def test_graphql_search_is_parsed_and_accessories_are_excluded():
    responses.add(responses.GET, GRAPHQL_URL, body=json.dumps(GRAPHQL_RESPONSE), status=200)
    responses.add(
        responses.GET,
        f"{BASE_URL}/p/245179/apple-iphone-17-256gb-storage-black",
        body=read_fixture("vijay_pdp.html"),
        status=200,
    )

    adapter = VijaySalesAdapter(ADAPTER_TEST_CONFIG)
    result = adapter.run(SearchQuery(model="iPhone 17"), crawl_id="test-crawl")

    assert result.ok is True
    assert len(result.listings) == 1  # the silicone case must be filtered out
    listing = result.listings[0]
    assert listing.sku == "245179"
    assert listing.selling_price == 79900
    assert listing.mrp == 82900
    assert listing.availability == "available"
    assert listing.rating == 4.8  # rating_summary 97 / 20 rounded to 1dp


@responses.activate
def test_bank_offer_enrichment_is_best_effort_and_never_fatal():
    responses.add(responses.GET, GRAPHQL_URL, body=json.dumps(GRAPHQL_RESPONSE), status=200)
    responses.add(
        responses.GET,
        f"{BASE_URL}/p/245179/apple-iphone-17-256gb-storage-black",
        status=500,  # PDP fetch fails - listing itself must still come through
    )

    adapter = VijaySalesAdapter(ADAPTER_TEST_CONFIG)
    result = adapter.run(SearchQuery(model="iPhone 17"), crawl_id="test-crawl")

    assert result.ok is True
    assert len(result.listings) == 1
    assert result.listings[0].offers == []  # enrichment failed silently, base listing intact


@responses.activate
def test_malformed_graphql_response_is_handled_gracefully():
    responses.add(responses.GET, GRAPHQL_URL, body="not json", status=200)

    adapter = VijaySalesAdapter(ADAPTER_TEST_CONFIG)
    result = adapter.run(SearchQuery(model="iPhone 17"), crawl_id="test-crawl")

    assert result.ok is False
    assert result.listings == []


def test_is_in_smartphones_category_true_for_real_phone():
    item = {
        "name": "Samsung Galaxy Z Flip7 (12GB RAM, 256GB Storage)",
        "categories": [
            {"url_key": "electronics"},
            {"url_key": "mobiles"},
            {"url_key": "smartphones"},
        ],
    }
    assert VijaySalesAdapter._is_in_smartphones_category(item) is True


def test_is_in_smartphones_category_false_for_text_search_false_positive():
    # Regression: a broad catalog-crawl search for "smartphone" also matches
    # products whose *name* contains the word but aren't phones - the site's
    # own category breadcrumb is what actually distinguishes them, not the
    # accessory keyword list (which can't anticipate every such case).
    item = {
        "name": "Fujifilm instax Mini Link 2 Smartphone Printer",
        "categories": [
            {"url_key": "electronics"},
            {"url_key": "camera-and-accessories"},
            {"url_key": "instant-camera"},
        ],
    }
    assert VijaySalesAdapter._is_in_smartphones_category(item) is False


def test_is_in_smartphones_category_false_when_categories_missing():
    assert VijaySalesAdapter._is_in_smartphones_category({"name": "Something"}) is False
