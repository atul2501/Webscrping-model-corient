"""Full-catalogue crawl across all registered sources - not a per-model
search, a deliberate sweep to capture as much of each site's live
smartphone catalogue as can be reached respectfully and within robots.txt.
This is the spec's optional "Scheduled refresh / background jobs" feature:
run this periodically (cron/manual) to build up a broad, queryable dataset
that outlives any single live search - once persisted, every listing here
is queryable through the normal /api/product and /api/price-history
endpoints like any other scraped data.

Realistic scale, verified while building this:
- Vijay Sales exposes real pagination on its public GraphQL search API -
  searching "smartphone" alone returns 1000+ results (accessories filtered
  out below) across ~11 pages at 100/page; "mobile phone" adds more.
- Reliance Digital has no bulk/paginated endpoint reachable under
  robots.txt (it disallows every query-string URL), so this sweeps every
  collection page the live adapter already knows about
  (app/scrapers/reliance_digital.py's MODEL_COLLECTION_SLUGS /
  BRAND_FALLBACK_SLUGS, plus the generic page) and de-duplicates by
  product URL.
- Croma is attempted for completeness but is expected to fail outright -
  Akamai's WAF blocks this environment's IP (see app/scrapers/croma.py's
  docstring for the full story). That is not a bug in this script.

This is hundreds of real listings, not "millions" - these retailers simply
don't carry that many distinct phone models. What this script guarantees is
respectful, complete coverage of what each site *actually* exposes, rather
than an arbitrary bigger number. It also skips the per-listing bank-offer
enrichment the live Vijay Sales search does for its top few results (that's
one extra HTTP request per listing - fine for ~5 results, not for hundreds)
so this stays fast and polite; those listings just persist without offer
text, which is a fair trade for bulk coverage.

Usage:
    python scripts/crawl_full_catalog.py
    python scripts/crawl_full_catalog.py --sources vijay_sales,reliance_digital
"""

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bs4 import BeautifulSoup

from app import create_app
from app.extensions import db
from app.models import CrawlRun
from app.scrapers.base import RawListing, SearchQuery, SourceBlockedError, SourceFetchError
from app.scrapers.croma import CromaAdapter
from app.scrapers.reliance_digital import ALL_CATALOG_COLLECTION_SLUGS
from app.scrapers.reliance_digital import BASE_URL as RD_BASE_URL
from app.scrapers.reliance_digital import RelianceDigitalAdapter
from app.scrapers.vijay_sales import VijaySalesAdapter
from app.services.search_service import _persist_listing

VIJAY_SALES_CATALOG_SEARCH_TERMS = ["smartphone", "mobile phone"]


def crawl_vijay_sales(adapter: VijaySalesAdapter, crawl_id: str) -> list[RawListing]:
    seen_skus: set[str] = set()
    listings: list[RawListing] = []

    for term in VIJAY_SALES_CATALOG_SEARCH_TERMS:
        page = 1
        while True:
            try:
                items, total_pages = adapter.fetch_catalog_page(term, page, crawl_id)
            except (SourceBlockedError, SourceFetchError) as exc:
                print(f"  [vijay_sales] '{term}' page {page} failed, stopping this term: {exc}")
                break

            for item in items:
                sku = item.get("sku")
                name = item.get("name") or ""
                if not sku or sku in seen_skus:
                    continue
                if adapter._looks_like_accessory(name) or not adapter._is_in_smartphones_category(item):
                    continue
                seen_skus.add(sku)
                listings.append(adapter._to_listing(item))

            print(f"  [vijay_sales] '{term}' page {page}/{total_pages} -> {len(seen_skus)} unique phones so far")
            if page >= total_pages:
                break
            page += 1

    return listings


def crawl_reliance_digital(adapter: RelianceDigitalAdapter, crawl_id: str) -> list[RawListing]:
    seen_urls: set[str] = set()
    listings: list[RawListing] = []
    slugs = ["smartphones", *ALL_CATALOG_COLLECTION_SLUGS]

    for slug in slugs:
        url = f"{RD_BASE_URL}/collection/{slug}"
        try:
            result = adapter.get(url, crawl_id=crawl_id)
        except (SourceBlockedError, SourceFetchError) as exc:
            print(f"  [reliance_digital] /collection/{slug} failed/skipped: {exc}")
            continue

        soup = BeautifulSoup(result.text, "lxml")
        found_here = 0
        for card in soup.select("div.product-card"):
            listing = adapter._parse_card(card)
            if listing is None or not listing.product_url or listing.product_url in seen_urls:
                continue
            seen_urls.add(listing.product_url)
            listings.append(listing)
            found_here += 1
        print(f"  [reliance_digital] /collection/{slug} -> {found_here} new ({len(seen_urls)} unique so far)")

    return listings


def crawl_croma(adapter: CromaAdapter, crawl_id: str) -> list[RawListing]:
    try:
        listings = adapter.search(SearchQuery(model=""), crawl_id)
        print(f"  [croma] {len(listings)} listing(s)")
        return listings
    except (SourceBlockedError, SourceFetchError) as exc:
        print(f"  [croma] blocked/failed - expected, see app/scrapers/croma.py's docstring: {exc}")
        return []


CRAWLERS = {
    "vijay_sales": (VijaySalesAdapter, crawl_vijay_sales),
    "reliance_digital": (RelianceDigitalAdapter, crawl_reliance_digital),
    "croma": (CromaAdapter, crawl_croma),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Full-catalogue crawl across all registered sources.")
    parser.add_argument("--sources", default=",".join(CRAWLERS.keys()), help="Comma-separated source names")
    args = parser.parse_args()
    requested = [s.strip() for s in args.sources.split(",") if s.strip()]

    app = create_app()
    with app.app_context():
        crawl_id = uuid.uuid4().hex
        crawl_run = CrawlRun(
            crawl_id=crawl_id,
            query_json=json.dumps({"mode": "full_catalog_crawl", "sources": requested}),
            sources_attempted=len(requested),
        )
        db.session.add(crawl_run)
        db.session.flush()

        total_persisted = 0
        succeeded = 0
        notes = []

        for source in requested:
            if source not in CRAWLERS:
                print(f"Unknown source '{source}', skipping")
                continue

            adapter_cls, crawl_fn = CRAWLERS[source]
            print(f"=== {source} ===")
            start = time.monotonic()
            adapter = adapter_cls(app.config)
            listings = crawl_fn(adapter, crawl_id)
            elapsed = time.monotonic() - start
            print(f"  {source}: {len(listings)} listing(s) in {elapsed:.1f}s\n")

            # Scraping (the slow, network-bound part) is fully done before any
            # DB write starts here, and this source's writes are one tight
            # transaction - same reasoning as search_service._run_crawl: never
            # hold a write transaction open across slow network I/O.
            for raw in listings:
                _persist_listing(raw, crawl_id)
            db.session.commit()

            total_persisted += len(listings)
            if listings:
                succeeded += 1
            notes.append(f"{source}: {len(listings)} listing(s) in {elapsed:.1f}s")

        crawl_run.finished_at = datetime.now(timezone.utc)
        crawl_run.sources_succeeded = succeeded
        crawl_run.sources_failed = len(requested) - succeeded
        crawl_run.notes = "; ".join(notes)
        db.session.commit()

        print(
            f"Done. crawl_id={crawl_id}, {total_persisted} listing(s) persisted "
            f"across {succeeded}/{len(requested)} source(s)."
        )


if __name__ == "__main__":
    main()
