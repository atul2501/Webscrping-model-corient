"""Seeds a small, offline demo dataset (no network calls) so an evaluator can
inspect /api/product, /api/offers and /api/price-history without first
running a live search. Safe to re-run - it's idempotent per crawl_id.

Usage: python scripts/seed_db.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models import CrawlRun, Listing, Offer, Product, Variant

SEED_CRAWL_ID = "seed-demo-crawl-0001"


def seed() -> None:
    app = create_app()
    with app.app_context():
        if CrawlRun.query.filter_by(crawl_id=SEED_CRAWL_ID).first() is not None:
            print("Seed data already present - nothing to do.")
            return

        product = Product(brand="Apple", model="iPhone 17 Pro", canonical_name="Apple iPhone 17 Pro")
        db.session.add(product)
        db.session.flush()

        variant = Variant(
            product_id=product.id,
            storage="256GB",
            colour="Cosmic Orange",
            variant_key="apple|iphone 17 pro|256|cosmic orange",
        )
        db.session.add(variant)
        db.session.flush()

        crawl_run = CrawlRun(
            crawl_id=SEED_CRAWL_ID,
            query_json='{"model": "iPhone 17 Pro", "seed": true}',
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
        history = [
            ("vijay_sales", 132990, 129590, now - timedelta(days=6)),
            ("reliance_digital", 131900, 128990, now - timedelta(days=6)),
            ("vijay_sales", 132990, 127990, now - timedelta(days=3)),
            ("reliance_digital", 131900, 128499, now - timedelta(days=3)),
            ("vijay_sales", 132990, 126990, now),
            ("reliance_digital", 131900, 127990, now),
        ]

        for source, mrp, selling_price, scraped_at in history:
            listing = Listing(
                variant_id=variant.id,
                source=source,
                product_name_raw=f"Apple iPhone 17 Pro (256GB Storage, Cosmic Orange) - {source}",
                sku="245195",
                product_url=f"https://example.com/{source}/iphone-17-pro",
                image_url=None,
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

            if scraped_at == now:
                db.session.add(
                    Offer(
                        listing_id=listing.id,
                        offer_text="10% instant discount up to Rs.4,000 on HDFC Bank Credit Cards",
                        offer_type="bank",
                        bank="HDFC",
                        offer_discount=4000,
                        emi_available=True,
                        emi_tenure=12,
                        emi_rate=0.0,
                        valid_till_text="Seed demo data",
                    )
                )

        db.session.commit()
        print(f"Seeded 1 product, 1 variant, {len(history)} listings under crawl_id={crawl_run.crawl_id}")


if __name__ == "__main__":
    seed()
