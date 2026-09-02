import uuid
from datetime import datetime, timezone

from app.extensions import db


def _uuid() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Product(db.Model):
    """A canonical product family, e.g. Apple / iPhone 17 Pro."""

    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(64), nullable=False, index=True)
    model = db.Column(db.String(128), nullable=False, index=True)
    canonical_name = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    variants = db.relationship("Variant", back_populates="product", cascade="all, delete-orphan")

    __table_args__ = (db.UniqueConstraint("brand", "model", name="uq_products_brand_model"),)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Product {self.brand} {self.model}>"


class Variant(db.Model):
    """A specific storage/colour variant of a Product, matched across sources."""

    __tablename__ = "variants"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    storage = db.Column(db.String(32), nullable=True)
    colour = db.Column(db.String(64), nullable=True)
    variant_key = db.Column(db.String(256), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    product = db.relationship("Product", back_populates="variants")
    listings = db.relationship("Listing", back_populates="variant", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Variant {self.variant_key}>"


class Listing(db.Model):
    """One scraped snapshot of a variant from one source at one point in time.

    Append-only by design: a new row is written on every crawl rather than
    updating an existing row, so historical price tracking (/api/price-history)
    is just a query over past rows for a variant_id.
    """

    __tablename__ = "listings"

    id = db.Column(db.Integer, primary_key=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("variants.id"), nullable=False, index=True)

    source = db.Column(db.String(64), nullable=False, index=True)
    product_name_raw = db.Column(db.String(300), nullable=False)
    sku = db.Column(db.String(128), nullable=True)
    product_url = db.Column(db.String(600), nullable=True)
    image_url = db.Column(db.String(600), nullable=True)

    currency = db.Column(db.String(8), nullable=False, default="INR")
    mrp = db.Column(db.Numeric(12, 2), nullable=True)
    selling_price = db.Column(db.Numeric(12, 2), nullable=True)
    discount = db.Column(db.Numeric(12, 2), nullable=True)
    availability = db.Column(db.String(32), nullable=True)
    seller = db.Column(db.String(120), nullable=True)

    rating = db.Column(db.Float, nullable=True)
    review_count = db.Column(db.Integer, nullable=True)

    crawl_id = db.Column(db.String(32), db.ForeignKey("crawl_runs.crawl_id"), nullable=False, index=True)
    scraped_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False, index=True)

    variant = db.relationship("Variant", back_populates="listings")
    offers = db.relationship("Offer", back_populates="listing", cascade="all, delete-orphan")
    crawl_run = db.relationship("CrawlRun", back_populates="listings")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Listing {self.source}:{self.sku}>"


class Offer(db.Model):
    """A raw, scraped offer fact attached to a listing (bank/card/EMI/exchange)."""

    __tablename__ = "offers"

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False, index=True)

    offer_text = db.Column(db.String(500), nullable=True)
    offer_type = db.Column(db.String(32), nullable=True)  # bank, card, exchange, no_cost_emi, other
    bank = db.Column(db.String(80), nullable=True)
    offer_discount = db.Column(db.Numeric(12, 2), nullable=True)

    emi_available = db.Column(db.Boolean, default=False, nullable=False)
    emi_tenure = db.Column(db.Integer, nullable=True)  # months, if the offer specifies one
    emi_rate = db.Column(db.Float, nullable=True)  # annual %, if the offer specifies one
    valid_till_text = db.Column(db.String(120), nullable=True)

    listing = db.relationship("Listing", back_populates="offers")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Offer {self.offer_type}:{self.bank}>"


class CrawlRun(db.Model):
    """Metadata for one search-triggered crawl across all adapters."""

    __tablename__ = "crawl_runs"

    id = db.Column(db.Integer, primary_key=True)
    crawl_id = db.Column(db.String(32), unique=True, nullable=False, default=_uuid, index=True)
    query_json = db.Column(db.Text, nullable=False)

    started_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)

    sources_attempted = db.Column(db.Integer, default=0, nullable=False)
    sources_succeeded = db.Column(db.Integer, default=0, nullable=False)
    sources_failed = db.Column(db.Integer, default=0, nullable=False)
    notes = db.Column(db.Text, nullable=True)

    listings = db.relationship("Listing", back_populates="crawl_run")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CrawlRun {self.crawl_id}>"


class SearchCache(db.Model):
    """Short-TTL cache mapping a normalized query to the crawl that answered it.

    Avoids re-scraping when the same search is repeated within the TTL window.
    """

    __tablename__ = "search_cache"

    id = db.Column(db.Integer, primary_key=True)
    query_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    crawl_id = db.Column(db.String(32), db.ForeignKey("crawl_runs.crawl_id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
