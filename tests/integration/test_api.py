"""End-to-end tests against the Flask API. The scraper registry is
monkeypatched with fake adapters so these run fully offline and
deterministically - no live network, no dependency on retailer sites being
reachable or unchanged.
"""

from app.scrapers.base import AdapterResult, BaseAdapter, RawListing, RawOffer, SearchQuery


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
    assert len(history_response.get_json()["history"]) == 1


def test_unknown_variant_and_listing_return_404(client):
    assert client.get("/api/product/999999").status_code == 404
    assert client.get("/api/offers/999999").status_code == 404
    assert client.get("/api/price-history/999999").status_code == 404


def test_index_page_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Price Intelligence" in response.data
