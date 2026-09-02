"""Orchestrates one end-to-end search: cache check -> dispatch adapters
concurrently -> persist raw listings -> match into variants -> price/EMI ->
rank -> build the response the API/UI renders.
"""

import concurrent.futures
import json
import logging
import uuid
from datetime import datetime, timezone

from app.extensions import db
from app.matching.matcher import get_or_create_variant
from app.matching.normalizer import parse_product_name
from app.models import CrawlRun, Listing, Offer, Product, Variant
from app.pricing.deal_score import DealScoreInputs, calculate_deal_score
from app.pricing.emi import calculate_emi, effective_price
from app.scrapers.base import AdapterResult, RawListing, SearchQuery
from app.scrapers.registry import SOURCE_ADAPTERS
from app.services.cache import get_cached_crawl_id, set_cache

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def run_search(params: dict, config) -> dict:
    query = SearchQuery(
        model=params["model"],
        storage=params.get("storage"),
        colour=params.get("colour"),
        budget_min=params.get("budget_min"),
        budget_max=params.get("budget_max"),
    )
    requested_sources = params.get("sources") or list(SOURCE_ADAPTERS.keys())
    requested_sources = [s for s in requested_sources if s in SOURCE_ADAPTERS]

    cache_key = {
        "model": query.model.lower().strip(),
        "storage": (query.storage or "").lower().strip(),
        "colour": (query.colour or "").lower().strip(),
        "budget_min": query.budget_min,
        "budget_max": query.budget_max,
        "sources": sorted(requested_sources),
    }

    cached_crawl_id = get_cached_crawl_id(cache_key, config["SEARCH_CACHE_TTL_SECONDS"])
    crawl_run = None
    if cached_crawl_id:
        crawl_run = CrawlRun.query.filter_by(crawl_id=cached_crawl_id).first()

    if crawl_run is None:
        crawl_run = _run_crawl(requested_sources, query, cache_key, config)
        set_cache(cache_key, crawl_run.crawl_id)

    return build_response(crawl_run, query, params, config)


def _run_crawl(requested_sources: list[str], query: SearchQuery, cache_key: dict, config) -> CrawlRun:
    adapters = [SOURCE_ADAPTERS[name](config) for name in requested_sources]

    # crawl_id is generated here, in Python, rather than left to the
    # CrawlRun model's column default - that default only applies once the
    # row is flushed, and flushing this early would open a write transaction
    # that then sits open for the entire multi-second scrape below. Under
    # concurrent searches on SQLite that reliably produced "database is
    # locked": one request's transaction would still be open (not yet
    # committed - commit only happened after scraping finished) by the time
    # a second request tried to insert its own CrawlRun row. Generating the
    # id up front means no DB write happens until *after* all the slow
    # network I/O is done, so the write transaction below is only open for
    # the time it takes to insert a handful of rows.
    crawl_id = uuid.uuid4().hex

    results = _dispatch(adapters, query, crawl_id, config["SCRAPE_MAX_WORKERS"])

    crawl_run = CrawlRun(crawl_id=crawl_id, query_json=json.dumps(cache_key), sources_attempted=len(adapters))
    db.session.add(crawl_run)
    db.session.flush()

    for result in results:
        for raw_listing in result.listings:
            _persist_listing(raw_listing, crawl_id)

    succeeded = sum(1 for r in results if r.ok)
    crawl_run.finished_at = _utcnow()
    crawl_run.sources_succeeded = succeeded
    crawl_run.sources_failed = len(results) - succeeded
    crawl_run.notes = "; ".join(
        f"{r.source}: {'ok (' + str(len(r.listings)) + ' listing(s))' if r.ok else (r.error or 'failed')}"
        for r in results
    )
    db.session.commit()
    return crawl_run


def _dispatch(adapters, query: SearchQuery, crawl_id: str, max_workers: int) -> list[AdapterResult]:
    results: list[AdapterResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        future_to_adapter = {executor.submit(adapter.run, query, crawl_id): adapter for adapter in adapters}
        for future in concurrent.futures.as_completed(future_to_adapter):
            adapter = future_to_adapter[future]
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 - one source's thread must never sink the search
                logger.exception("adapter thread for %s crashed unexpectedly", adapter.source_name)
                results.append(AdapterResult(source=adapter.source_name, ok=False, error=str(exc)))
    return results


def _persist_listing(raw: RawListing, crawl_id: str) -> None:
    parsed = parse_product_name(
        raw.product_name_raw,
        colour_hint=raw.colour_hint,
        storage_hint=raw.storage_hint,
        brand_hint=raw.brand_hint,
    )
    variant = get_or_create_variant(parsed)

    listing = Listing(
        variant_id=variant.id,
        source=raw.source,
        product_name_raw=raw.product_name_raw,
        sku=raw.sku,
        product_url=raw.product_url,
        image_url=raw.image_url,
        currency=raw.currency,
        mrp=raw.mrp,
        selling_price=raw.selling_price,
        discount=raw.discount,
        availability=raw.availability,
        seller=raw.seller,
        rating=raw.rating,
        review_count=raw.review_count,
        crawl_id=crawl_id,
    )
    db.session.add(listing)
    db.session.flush()

    for raw_offer in raw.offers:
        db.session.add(
            Offer(
                listing_id=listing.id,
                offer_text=raw_offer.offer_text,
                offer_type=raw_offer.offer_type,
                bank=raw_offer.bank,
                offer_discount=raw_offer.offer_discount,
                emi_available=raw_offer.emi_available,
                emi_tenure=raw_offer.emi_tenure,
                emi_rate=raw_offer.emi_rate,
                valid_till_text=raw_offer.valid_till_text,
            )
        )


def _passes_filters(listing: Listing, query: SearchQuery) -> bool:
    if query.storage and listing.variant.storage:
        if query.storage.lower().replace(" ", "") not in listing.variant.storage.lower().replace(" ", ""):
            return False
    if query.colour and listing.variant.colour:
        if query.colour.lower() not in listing.variant.colour.lower():
            return False
    if query.budget_min is not None and listing.selling_price is not None:
        if float(listing.selling_price) < query.budget_min:
            return False
    if query.budget_max is not None and listing.selling_price is not None:
        if float(listing.selling_price) > query.budget_max:
            return False
    return True


def _num(value) -> float | None:
    return float(value) if value is not None else None


def _display_source(source: str) -> str:
    """The API identifies retailers by their internal slug (matches
    scraper.source_name / SOURCE_ADAPTERS, e.g. "vijay_sales") everywhere
    it's used as a value - the "source" fields on best_current_price etc.
    stay that slug so it round-trips with the sources filter. This is only
    for the "reason" sentence, which is prose meant to be read as-is."""
    return source.replace("_", " ").title()


def build_response(crawl_run: CrawlRun, query: SearchQuery, params: dict, config) -> dict:
    listings = (
        Listing.query.filter_by(crawl_id=crawl_run.crawl_id)
        .join(Variant, Listing.variant_id == Variant.id)
        .join(Product, Variant.product_id == Product.id)
        .all()
    )
    listings = [listing for listing in listings if _passes_filters(listing, query)]

    tenure_months = int(params.get("emi_tenure_months") or config["EMI_DEFAULT_TENURE_MONTHS"])
    down_payment = float(params.get("down_payment") or 0)
    annual_rate = float(
        params.get("emi_annual_rate_percent")
        if params.get("emi_annual_rate_percent") is not None
        else config["EMI_DEFAULT_ANNUAL_RATE_PERCENT"]
    )

    entries = []
    for listing in listings:
        offer_discounts = [float(o.offer_discount) for o in listing.offers if o.offer_discount is not None]
        selling = _num(listing.selling_price)
        eff_price = effective_price(selling, offer_discounts) if selling is not None else None

        no_cost = any(o.offer_type == "no_cost_emi" for o in listing.offers)
        emi_scenario = None
        if eff_price is not None and tenure_months > 0:
            financed = max(eff_price - down_payment, 0)
            emi_scenario = calculate_emi(financed, tenure_months, annual_rate, no_cost_emi=no_cost)

        entries.append({"listing": listing, "effective_price": eff_price, "emi": emi_scenario})

    priced = [e for e in entries if e["effective_price"] is not None]
    lo = min((e["effective_price"] for e in priced), default=0.0)
    hi = max((e["effective_price"] for e in priced), default=0.0)

    for entry in entries:
        if entry["effective_price"] is None:
            entry["deal_score"] = None
            continue
        listing = entry["listing"]
        discount_percent = 0.0
        if listing.mrp and float(listing.mrp) > 0:
            discount_percent = max(0.0, (float(listing.mrp) - entry["effective_price"]) / float(listing.mrp) * 100)
        entry["deal_score"] = calculate_deal_score(
            DealScoreInputs(
                effective_price=entry["effective_price"],
                lowest_effective_price_in_group=lo,
                highest_effective_price_in_group=hi,
                discount_percent=discount_percent,
                availability=listing.availability,
                source=listing.source,
            )
        )

    entries.sort(key=lambda e: (e["effective_price"] is None, e["effective_price"] or 0.0))

    return {
        "crawl_id": crawl_run.crawl_id,
        "query": {
            "model": query.model,
            "storage": query.storage,
            "colour": query.colour,
            "budget_min": query.budget_min,
            "budget_max": query.budget_max,
        },
        "emi_assumptions": {
            "tenure_months": tenure_months,
            "down_payment": down_payment,
            "annual_rate_percent": annual_rate,
            "note": "EMI figures are calculated estimates, not scraped facts.",
        },
        "sources_attempted": crawl_run.sources_attempted,
        "sources_succeeded": crawl_run.sources_succeeded,
        "sources_failed": crawl_run.sources_failed,
        "source_notes": crawl_run.notes,
        "scraped_at": crawl_run.finished_at.isoformat() if crawl_run.finished_at else None,
        "results": [_serialize_entry(e) for e in entries],
        "recommendation": _build_recommendation(entries),
    }


def _serialize_entry(entry: dict) -> dict:
    listing: Listing = entry["listing"]
    variant = listing.variant
    product = variant.product
    emi = entry["emi"]

    return {
        "listing_id": listing.id,
        "variant_id": variant.id,
        "product": {"brand": product.brand, "model": product.model},
        "variant": {"storage": variant.storage, "colour": variant.colour},
        "source": listing.source,
        "product_name": listing.product_name_raw,
        "product_url": listing.product_url,
        "image_url": listing.image_url,
        "currency": listing.currency,
        "mrp": _num(listing.mrp),
        "selling_price": _num(listing.selling_price),
        "discount": _num(listing.discount),
        "effective_price": entry["effective_price"],
        "availability": listing.availability,
        "seller": listing.seller,
        "rating": listing.rating,
        "review_count": listing.review_count,
        "offers": [
            {
                "offer_text": o.offer_text,
                "offer_type": o.offer_type,
                "bank": o.bank,
                "offer_discount": _num(o.offer_discount),
                "emi_available": o.emi_available,
                "valid_till_text": o.valid_till_text,
            }
            for o in listing.offers
        ],
        "emi": None
        if emi is None
        else {
            "tenure_months": emi.tenure_months,
            "annual_rate_percent": emi.annual_rate_percent,
            "monthly_emi": emi.monthly_emi,
            "total_repayment": emi.total_repayment,
            "total_interest": emi.total_interest,
            "is_no_cost_emi": emi.is_no_cost_emi,
            "estimate": emi.estimate,
        },
        "deal_score": entry["deal_score"],
        "scraped_at": listing.scraped_at.isoformat() if listing.scraped_at else None,
    }


def _build_recommendation(entries: list[dict]) -> dict | None:
    priced = [e for e in entries if e["effective_price"] is not None]
    if not priced:
        return None

    best_price_entry = min(priced, key=lambda e: _num(e["listing"].selling_price) or float("inf"))
    best_effective_entry = priced[0]  # entries are pre-sorted by effective_price ascending
    with_emi = [e for e in priced if e["emi"] is not None]
    lowest_emi_entry = min(with_emi, key=lambda e: e["emi"].monthly_emi, default=None)

    return {
        "best_current_price": {
            "source": best_price_entry["listing"].source,
            "amount": _num(best_price_entry["listing"].selling_price),
        },
        "best_effective_price": {
            "source": best_effective_entry["listing"].source,
            "amount": best_effective_entry["effective_price"],
        },
        "lowest_emi": None
        if lowest_emi_entry is None
        else {
            "source": lowest_emi_entry["listing"].source,
            "monthly_emi": lowest_emi_entry["emi"].monthly_emi,
            "tenure_months": lowest_emi_entry["emi"].tenure_months,
        },
        "reason": (
            f"{_display_source(best_effective_entry['listing'].source)} has the lowest effective price "
            f"(Rs.{best_effective_entry['effective_price']:,.0f}) after applicable offers, "
            f"across {len(priced)} matched listing(s) from "
            f"{len({e['listing'].source for e in priced})} source(s)."
        ),
    }
