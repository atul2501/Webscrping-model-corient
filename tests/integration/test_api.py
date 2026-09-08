"""End-to-end tests against the Flask API. The scraper registry is
monkeypatched with fake adapters so these run fully offline and
deterministically - no live network, no dependency on retailer sites being
reachable or unchanged.
"""

from app.scrapers.base import BaseAdapter, RawListing, RawOffer, SearchQuery


class _FakeOkAdapter(BaseAdapter):
    source_name = "fake_ok"
    domain = "fake-ok.example"

    def search(self, query: SearchQuery, crawl_id: str) -> list[RawListing]:
        return [
            RawListing(
                source=self.source_name,
                product_name_raw="Apple iPhone 17 Pro (256GB Storage, Black)",
                sku="SKU1",
                product_url="https://fake-ok.example/p/1",
                mrp=139900,
                selling_price=129900,
                discount=10000,
                availability="available",
                seller="Fake OK",
                rating=4.5,
                review_count=10,
                offers=[
                    RawOffer(
                        offer_text="10% off with HDFC cards, up to Rs.4000",
                        offer_type="bank",
                        bank="HDFC",
                        offer_discount=4000,
                        emi_available=True,
                        emi_tenure=12,
                        emi_rate=13.5,
                    )
                ],
            )
        ]


class _FakeCheaperAdapter(BaseAdapter):
    source_name = "fake_cheaper"
    domain = "fake-cheaper.example"

    def search(self, query: SearchQuery, crawl_id: str) -> list[RawListing]:
        return [
            RawListing(
                source=self.source_name,
                product_name_raw="Apple iPhone 17 Pro (256GB Storage, Black)",
                sku="SKU2",
                product_url="https://fake-cheaper.example/p/1",
                mrp=139900,
                selling_price=124900,
                discount=15000,
                availability="available",
                seller="Fake Cheaper",
            )
        ]


class _FakeFailingAdapter(BaseAdapter):
    source_name = "fake_failing"
    domain = "fake-failing.example"

    def search(self, query: SearchQuery, crawl_id: str) -> list[RawListing]:
        raise RuntimeError("simulated source outage")


class _FakePriceDropAdapter(BaseAdapter):
    """Returns the same SKU/variant at a lower price on each successive
    call, so two back-to-back crawls land two Listing rows for one Variant
    at different prices - what the price-history endpoint's drop detection
    is meant to catch.

    `_call_count` is a *class* attribute, not instance state: search_service
    builds a fresh adapter instance for every crawl, so instance state alone
    would reset to call #0 on each search and never reach the second price.
    Tests using this must reset it (`_FakePriceDropAdapter._call_count = 0`)
    before use, since it's shared across the whole test session otherwise.
    """

    source_name = "fake_drop"
    domain = "fake-drop.example"
    prices = [129900, 119900]
    _call_count = 0

    def search(self, query: SearchQuery, crawl_id: str) -> list[RawListing]:
        price = _FakePriceDropAdapter.prices[min(_FakePriceDropAdapter._call_count, len(_FakePriceDropAdapter.prices) - 1)]
        _FakePriceDropAdapter._call_count += 1
        return [
            RawListing(
                source=self.source_name,
                product_name_raw="Apple iPhone 17 Pro (256GB Storage, Black)",
                sku="SKU-DROP",
                product_url="https://fake-drop.example/p/1",
                mrp=139900,
                selling_price=price,
                availability="available",
                seller="Fake Drop",
            )
        ]


def _patch_registry(monkeypatch, adapters: dict):
    monkeypatch.setattr("app.services.search_service.SOURCE_ADAPTERS", adapters)


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"


def test_search_requires_model(client):
    response = client.post("/api/search", json={})
    assert response.status_code == 400
    assert "model" in response.get_json()["error"]


def test_search_rejects_non_positive_emi_tenure(client):
    response = client.post("/api/search", json={"model": "iPhone 17 Pro", "emi_tenure_months": 0})
    assert response.status_code == 400
    assert "emi_tenure_months" in response.get_json()["error"]

    response = client.post("/api/search", json={"model": "iPhone 17 Pro", "emi_tenure_months": -6})
    assert response.status_code == 400
    assert "emi_tenure_months" in response.get_json()["error"]


def test_search_rejects_non_numeric_emi_tenure(client):
    response = client.post("/api/search", json={"model": "iPhone 17 Pro", "emi_tenure_months": "twelve"})
    assert response.status_code == 400
    assert "emi_tenure_months" in response.get_json()["error"]


def test_search_rejects_fractional_emi_tenure(client):
    # Regression guard: emi_tenure_months=3.7 must be rejected, not silently
    # truncated to 3 months via int().
    response = client.post("/api/search", json={"model": "iPhone 17 Pro", "emi_tenure_months": 3.7})
    assert response.status_code == 400
    assert "emi_tenure_months" in response.get_json()["error"]


def test_search_rejects_boolean_emi_tenure(client):
    # bool is a subclass of int in Python - int(True) == 1 would otherwise
    # silently accept `emi_tenure_months: true` as a valid 1-month tenure.
    response = client.post("/api/search", json={"model": "iPhone 17 Pro", "emi_tenure_months": True})
    assert response.status_code == 400
    assert "emi_tenure_months" in response.get_json()["error"]


def test_search_rejects_negative_down_payment(client):
    response = client.post("/api/search", json={"model": "iPhone 17 Pro", "down_payment": -100})
    assert response.status_code == 400
    assert "down_payment" in response.get_json()["error"]


def test_search_rejects_negative_emi_rate(client):
    response = client.post("/api/search", json={"model": "iPhone 17 Pro", "emi_annual_rate_percent": -1})
    assert response.status_code == 400
    assert "emi_annual_rate_percent" in response.get_json()["error"]


def test_search_rejects_excessive_emi_tenure(client):
    response = client.post("/api/search", json={"model": "iPhone 17 Pro", "emi_tenure_months": 999999})
    assert response.status_code == 400
    assert "emi_tenure_months" in response.get_json()["error"]


def test_search_rejects_excessive_emi_rate(client):
    response = client.post("/api/search", json={"model": "iPhone 17 Pro", "emi_annual_rate_percent": 10000})
    assert response.status_code == 400
    assert "emi_annual_rate_percent" in response.get_json()["error"]


def test_model_suggestions_match_prefix(client):
    response = client.get("/api/models?q=iphone 17")
    assert response.status_code == 200
    models = response.get_json()["models"]
    assert models  # at least one suggestion
    assert all("iphone 17" in m.lower() for m in models)


def test_model_suggestions_empty_query_returns_some_default_list(client):
    response = client.get("/api/models")
    assert response.status_code == 200
    assert len(response.get_json()["models"]) > 0


def test_model_options_is_instant_no_adapters_touched(client, monkeypatch):
    # Regression guard: this endpoint must never trigger a live scrape - if
    # it did, this would time out/fail since no adapter is registered here.
    monkeypatch.setattr("app.services.search_service.SOURCE_ADAPTERS", {})

    response = client.get("/api/model-options?model=iPhone 16")
    assert response.status_code == 200
    body = response.get_json()
    assert "128GB" in body["storage"]
    assert "Ultramarine" in body["colour"]


def test_search_returns_ranked_results_with_effective_price_and_emi(client, monkeypatch):
    _patch_registry(monkeypatch, {"fake_ok": _FakeOkAdapter, "fake_cheaper": _FakeCheaperAdapter})

    response = client.post(
        "/api/search",
        json={"model": "iPhone 17 Pro", "emi_tenure_months": 12, "down_payment": 20000},
    )
    assert response.status_code == 200
    body = response.get_json()

    assert body["sources_attempted"] == 2
    assert body["sources_succeeded"] == 2
    assert len(body["results"]) == 2

    # Ranked ascending by effective price: fake_cheaper (124900, no offer)
    # vs fake_ok (129900 - 4000 offer = 125900) -> fake_cheaper wins.
    assert body["results"][0]["source"] == "fake_cheaper"
    assert body["results"][0]["effective_price"] == 124900
    assert body["results"][1]["source"] == "fake_ok"
    assert body["results"][1]["effective_price"] == 125900

    emi = body["results"][0]["emi"]
    assert emi["estimate"] is True
    assert emi["tenure_months"] == 12
    assert emi["monthly_emi"] > 0

    assert body["recommendation"]["best_effective_price"]["source"] == "fake_cheaper"

    # Regression: sku (captured but never serialized anywhere) and
    # emi_tenure/emi_rate (present on /api/product and /api/offers but
    # missing here specifically) were both silent gaps against the spec's
    # "Data to Capture" list, found in a full audit pass.
    fake_ok_result = body["results"][1]
    assert fake_ok_result["source"] == "fake_ok"
    assert fake_ok_result["sku"] == "SKU1"
    fake_ok_offer = fake_ok_result["offers"][0]
    assert fake_ok_offer["emi_tenure"] == 12
    assert fake_ok_offer["emi_rate"] == 13.5


def test_search_pagination_slices_results(client, app, monkeypatch):
    monkeypatch.setitem(app.config, "RESULTS_PAGE_SIZE", 1)
    _patch_registry(monkeypatch, {"fake_ok": _FakeOkAdapter, "fake_cheaper": _FakeCheaperAdapter})

    first_page = client.post("/api/search", json={"model": "iPhone 17 Pro"})
    assert first_page.status_code == 200
    first_body = first_page.get_json()
    assert len(first_body["results"]) == 1
    assert first_body["results"][0]["source"] == "fake_cheaper"  # cheapest first
    assert first_body["result_page"] == 1
    assert first_body["result_page_size"] == 1
    assert first_body["total_results"] == 2
    assert first_body["total_pages"] == 2

    second_page = client.post("/api/search", json={"model": "iPhone 17 Pro", "result_page": 2})
    assert second_page.status_code == 200
    second_body = second_page.get_json()
    assert len(second_body["results"]) == 1
    assert second_body["results"][0]["source"] == "fake_ok"
    assert second_body["result_page"] == 2


def test_search_recommendation_reflects_full_result_set_not_just_current_page(client, app, monkeypatch):
    monkeypatch.setitem(app.config, "RESULTS_PAGE_SIZE", 1)
    _patch_registry(monkeypatch, {"fake_ok": _FakeOkAdapter, "fake_cheaper": _FakeCheaperAdapter})

    # Page 2 only contains fake_ok's listing, but the recommendation must
    # still reflect the overall best deal across the full crawl.
    response = client.post("/api/search", json={"model": "iPhone 17 Pro", "result_page": 2})
    assert response.status_code == 200
    body = response.get_json()
    assert body["results"][0]["source"] == "fake_ok"
    assert body["recommendation"]["best_effective_price"]["source"] == "fake_cheaper"


def test_search_result_page_beyond_last_page_returns_empty_results_not_error(client, monkeypatch):
    _patch_registry(monkeypatch, {"fake_ok": _FakeOkAdapter, "fake_cheaper": _FakeCheaperAdapter})

    response = client.post("/api/search", json={"model": "iPhone 17 Pro", "result_page": 100})
    assert response.status_code == 200
    body = response.get_json()
    assert body["results"] == []
    assert body["total_results"] == 2


def test_search_rejects_non_positive_result_page(client, monkeypatch):
    _patch_registry(monkeypatch, {"fake_ok": _FakeOkAdapter})
    response = client.post("/api/search", json={"model": "iPhone 17 Pro", "result_page": 0})
    assert response.status_code == 400
    assert "result_page" in response.get_json()["error"]


def test_search_rejects_non_integer_result_page(client, monkeypatch):
    _patch_registry(monkeypatch, {"fake_ok": _FakeOkAdapter})
    response = client.post("/api/search", json={"model": "iPhone 17 Pro", "result_page": "two"})
    assert response.status_code == 400
    assert "result_page" in response.get_json()["error"]


def test_search_rejects_result_page_size_over_max(client, app, monkeypatch):
    _patch_registry(monkeypatch, {"fake_ok": _FakeOkAdapter})
    response = client.post(
        "/api/search",
        json={"model": "iPhone 17 Pro", "result_page_size": app.config["RESULTS_MAX_PAGE_SIZE"] + 1},
    )
    assert response.status_code == 400
    assert "result_page_size" in response.get_json()["error"]


def test_search_rejects_non_positive_page(client, monkeypatch):
    _patch_registry(monkeypatch, {"fake_ok": _FakeOkAdapter})
    response = client.post("/api/search", json={"model": "iPhone 17 Pro", "page": 0})
    assert response.status_code == 400
    assert "'page'" in response.get_json()["error"]


def test_one_source_failing_does_not_break_the_search(client, monkeypatch):
    _patch_registry(monkeypatch, {"fake_ok": _FakeOkAdapter, "fake_failing": _FakeFailingAdapter})

    response = client.post("/api/search", json={"model": "iPhone 17 Pro"})
    assert response.status_code == 200
    body = response.get_json()

    assert body["sources_attempted"] == 2
    assert body["sources_succeeded"] == 1
    assert body["sources_failed"] == 1
    assert len(body["results"]) == 1
    assert body["results"][0]["source"] == "fake_ok"


def test_repeated_identical_search_hits_cache_not_a_fresh_crawl(client, monkeypatch, app):
    call_count = {"n": 0}

    class _CountingAdapter(_FakeOkAdapter):
        def search(self, query, crawl_id):
            call_count["n"] += 1
            return super().search(query, crawl_id)

    _patch_registry(monkeypatch, {"fake_ok": _CountingAdapter})
    app.config["SEARCH_CACHE_TTL_SECONDS"] = 900

    first = client.post("/api/search", json={"model": "iPhone 17 Pro"})
    second = client.post("/api/search", json={"model": "iPhone 17 Pro"})

    assert first.status_code == 200 and second.status_code == 200
    assert call_count["n"] == 1
    assert first.get_json()["crawl_id"] == second.get_json()["crawl_id"]


def test_product_offers_and_price_history_endpoints(client, monkeypatch):
    _patch_registry(monkeypatch, {"fake_ok": _FakeOkAdapter})

    search_response = client.post("/api/search", json={"model": "iPhone 17 Pro"})
    variant_id = search_response.get_json()["results"][0]["variant_id"]
    listing_id = search_response.get_json()["results"][0]["listing_id"]

    product_response = client.get(f"/api/product/{variant_id}")
    assert product_response.status_code == 200
    assert product_response.get_json()["product"]["brand"] == "Apple"

    offers_response = client.get(f"/api/offers/{listing_id}")
    assert offers_response.status_code == 200
    offers = offers_response.get_json()["offers"]
    assert len(offers) == 1
    assert offers[0]["bank"] == "HDFC"

    history_response = client.get(f"/api/price-history/{variant_id}")
    assert history_response.status_code == 200
    history_body = history_response.get_json()
    assert len(history_body["history"]) == 1
    assert history_body["product"]["brand"] == "Apple"
    assert history_body["price_drops"] == []  # a single scrape is never a drop


def test_price_drop_detected_across_two_crawls(client, monkeypatch, app):
    _FakePriceDropAdapter._call_count = 0
    _patch_registry(monkeypatch, {"fake_drop": _FakePriceDropAdapter})
    app.config["SEARCH_CACHE_TTL_SECONDS"] = 0  # force a fresh crawl each call, not a cache hit

    first = client.post("/api/search", json={"model": "iPhone 17 Pro"})
    variant_id = first.get_json()["results"][0]["variant_id"]
    assert first.get_json()["results"][0]["selling_price"] == 129900

    second = client.post("/api/search", json={"model": "iPhone 17 Pro"})
    assert second.get_json()["results"][0]["selling_price"] == 119900

    history = client.get(f"/api/price-history/{variant_id}").get_json()
    assert len(history["history"]) == 2
    assert len(history["price_drops"]) == 1
    drop = history["price_drops"][0]
    assert drop["source"] == "fake_drop"
    assert drop["previous_price"] == 129900
    assert drop["current_price"] == 119900
    assert drop["drop_amount"] == 10000


def test_unknown_variant_and_listing_return_404(client):
    assert client.get("/api/product/999999").status_code == 404
    assert client.get("/api/offers/999999").status_code == 404
    assert client.get("/api/price-history/999999").status_code == 404


def test_index_page_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Price Intelligence" in response.data
