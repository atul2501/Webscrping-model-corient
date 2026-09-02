"""Seeds a small, offline demo dataset (no network calls) so an evaluator can
inspect /api/product, /api/offers and /api/price-history - with a real,
multi-day price trend to chart - without first running several live
searches over time to build one up naturally.

Runs raw titles through the same app.matching.normalizer/matcher pipeline
_persist_listing() uses for real scraped data, rather than hand-writing
variant_key strings - so this stays correct if normalization logic ever
changes, and if a variant already exists (e.g. from a live search run
before this script), the seeded history is added onto it instead of
creating a duplicate.

Safe to re-run - idempotent per crawl_id.

Usage: python scripts/seed_db.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.matching.matcher import get_or_create_variant
from app.matching.normalizer import parse_product_name
from app.models import CrawlRun, Listing, Offer

SEED_CRAWL_ID = "seed-demo-crawl-0001"

# One entry per demo product: a raw title in the same comma/paren shape
# real adapters produce (see normalizer.py's docstring), and a per-source
# price trend as (mrp, selling_price, days_ago) tuples, oldest first -
# each trending downward, so every seeded product shows a genuine price
# drop when charted, not just a flat line.
DEMO_PRODUCTS = [
    {
        "raw_name": "Apple iPhone 17 Pro (256GB Storage, Cosmic Orange)",
        "trend": {
            "vijay_sales": [(132990, 129590, 6), (132990, 127990, 3), (132990, 126990, 0)],
            "reliance_digital": [(131900, 128990, 6), (131900, 128499, 3), (131900, 127990, 0)],
        },
        "offer": {"bank": "HDFC", "text": "10% instant discount up to Rs.4,000 on HDFC Bank Credit Cards", "discount": 4000},
    },
    {
        "raw_name": "Apple iPhone 16 (128GB Storage, Black)",
        "trend": {
            "vijay_sales": [(69900, 68900, 5), (69900, 67900, 2), (69900, 66900, 0)],
            "reliance_digital": [(69900, 69900, 5), (69900, 68900, 2), (69900, 64900, 0)],
        },
        "offer": {"bank": "ICICI", "text": "5% cashback up to Rs.2,000 on ICICI Bank Credit Cards", "discount": 2000},
    },
    {
        "raw_name": "Samsung Galaxy S24 Ultra 256 GB, Titanium Black",
        "trend": {
            "vijay_sales": [(129999, 124999, 5), (129999, 121999, 2), (129999, 119999, 0)],
            "reliance_digital": [(129999, 126999, 5), (129999, 122999, 0)],
        },
        "offer": {"bank": "HDFC", "text": "10% instant discount up to Rs.5,000 on HDFC Bank Credit Cards", "discount": 5000},
    },
    {
        "raw_name": "Google Pixel 9 Pro 256 GB, Obsidian",
        "trend": {
            "vijay_sales": [(99900, 96900, 4), (99900, 94900, 0)],
            "reliance_digital": [(99900, 97900, 4), (99900, 93900, 0)],
        },
        "offer": None,
    },
]


def seed() -> None:
    app = create_app()
    with app.app_context():
        if CrawlRun.query.filter_by(crawl_id=SEED_CRAWL_ID).first() is not None:
            print("Seed data already present - nothing to do.")
            return

        crawl_run = CrawlRun(
            crawl_id=SEED_CRAWL_ID,
            query_json='{"seed": true}',
            started_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            finished_at=datetime.now(timezone.utc),
            sources_attempted=3,
            sources_succeeded=2,
            sources_failed=1,
            notes="seed data for offline demo",
        )
        db.session.add(crawl_run)
        db.session.flush()

        now = datetime.now(timezone.utc)
        total_listings = 0

        for demo in DEMO_PRODUCTS:
            parsed = parse_product_name(demo["raw_name"])
            variant = get_or_create_variant(parsed)
            slug = parsed.model.lower().replace(" ", "-")

            for source, points in demo["trend"].items():
                for mrp, selling_price, days_ago in points:
                    scraped_at = now - timedelta(days=days_ago)
                    listing = Listing(
                        variant_id=variant.id,
                        source=source,
                        product_name_raw=f"{demo['raw_name']} - {source}",
                        sku=f"seed-{variant.id}",
                        product_url=f"https://example.com/{source}/{slug}",
                        currency="INR",
                        mrp=mrp,
                        selling_price=selling_price,
                        discount=mrp - selling_price,
                        availability="available",
                        seller=source.replace("_", " ").title(),
                        rating=4.5,
                        review_count=120,
                        crawl_id=crawl_run.crawl_id,
                        scraped_at=scraped_at,
                    )
                    db.session.add(listing)
                    db.session.flush()
                    total_listings += 1

                    # Only the most recent scrape carries a live-looking
                    # offer - older historical points are price-only, same
                    # as what a real re-scrape would capture.
                    if demo["offer"] and days_ago == 0:
                        db.session.add(
                            Offer(
                                listing_id=listing.id,
                                offer_text=demo["offer"]["text"],
                                offer_type="bank",
                                bank=demo["offer"]["bank"],
                                offer_discount=demo["offer"]["discount"],
                                emi_available=True,
                                emi_tenure=12,
                                emi_rate=0.0,
                                valid_till_text="Seed demo data",
                            )
                        )

        db.session.commit()
        print(f"Seeded {len(DEMO_PRODUCTS)} product(s), {total_listings} listings under crawl_id={crawl_run.crawl_id}")


if __name__ == "__main__":
    seed()
