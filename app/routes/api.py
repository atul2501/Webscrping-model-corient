from dataclasses import asdict

from flask import Blueprint, current_app, jsonify, request

from app.data.model_catalog import get_model_options, suggest_models
from app.extensions import db
from app.models import Listing, Product, Variant
from app.pricing.price_drop import detect_price_drops
from app.services.search_service import run_search

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _num(value) -> float | None:
    return float(value) if value is not None else None


def _to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _serialize_offer(offer) -> dict:
    return {
        "offer_text": offer.offer_text,
        "offer_type": offer.offer_type,
        "bank": offer.bank,
        "offer_discount": _num(offer.offer_discount),
        "emi_available": offer.emi_available,
        "emi_tenure": offer.emi_tenure,
        "emi_rate": offer.emi_rate,
        "valid_till_text": offer.valid_till_text,
    }


def _serialize_listing_brief(listing) -> dict:
    return {
        "listing_id": listing.id,
        "source": listing.source,
        "product_name": listing.product_name_raw,
        "product_url": listing.product_url,
        "image_url": listing.image_url,
        "mrp": _num(listing.mrp),
        "selling_price": _num(listing.selling_price),
        "availability": listing.availability,
        "seller": listing.seller,
        "rating": listing.rating,
        "review_count": listing.review_count,
        "scraped_at": listing.scraped_at.isoformat() if listing.scraped_at else None,
        "offers": [_serialize_offer(o) for o in listing.offers],
    }


@api_bp.get("/models")
def model_suggestions():
    """Autocomplete suggestions for the model field: whatever has actually
    been scraped and stored (Product.canonical_name) takes priority, topped
    up with a small curated static list so common models still suggest
    before any crawl has ever run. Search itself never depends on this list -
    it's suggestions only.
    """
    query = request.args.get("q", "").strip()

    scraped = (
        db.session.query(Product.canonical_name)
        .filter(Product.canonical_name.ilike(f"%{query}%"))
        .distinct()
        .order_by(Product.canonical_name)
        .limit(20)
        .all()
    )
    scraped_names = [row[0] for row in scraped]
    seen = {name.lower() for name in scraped_names}

    static_names = [name for name in suggest_models(query, limit=20) if name.lower() not in seen]

    return jsonify({"models": (scraped_names + static_names)[:10]})


@api_bp.get("/model-options")
def model_options():
    """Instant, no-scraping lookup of typical storage/colour choices for a
    model, used to populate the search form's dropdowns the moment a model
    is picked. This is a static catalog, not live availability - hitting
    Search still runs the real cross-source lookup that confirms what's
    actually in stock and at what price.
    """
    model = request.args.get("model", "")
    return jsonify(get_model_options(model))


@api_bp.post("/search")
def search():
    payload = request.get_json(silent=True) or {}
    model = (payload.get("model") or "").strip()
    if not model:
        return jsonify({"error": "'model' is required"}), 400

    params = {
        "model": model,
        "storage": payload.get("storage"),
        "colour": payload.get("colour"),
        "budget_min": _to_float(payload.get("budget_min")),
        "budget_max": _to_float(payload.get("budget_max")),
        "emi_tenure_months": payload.get("emi_tenure_months"),
        "down_payment": payload.get("down_payment"),
        "emi_annual_rate_percent": payload.get("emi_annual_rate_percent"),
        "sources": payload.get("sources"),
        "page": payload.get("page"),
    }

    try:
        result = run_search(params, current_app.config)
    except Exception:  # noqa: BLE001 - a bad search must return JSON, not a 500 HTML page
        current_app.logger.exception("search failed unexpectedly")
        return jsonify({"error": "search failed"}), 500

    return jsonify(result)


@api_bp.get("/product/<int:variant_id>")
def product_detail(variant_id: int):
    variant = db.session.get(Variant, variant_id)
    if variant is None:
        return jsonify({"error": "not found"}), 404
    product = variant.product

    latest_by_source: dict[str, Listing] = {}
    for listing in sorted(variant.listings, key=lambda item: item.scraped_at, reverse=True):
        latest_by_source.setdefault(listing.source, listing)

    return jsonify(
        {
            "variant_id": variant.id,
            "product": {"brand": product.brand, "model": product.model},
            "variant": {"storage": variant.storage, "colour": variant.colour},
            "latest_listings": [_serialize_listing_brief(listing) for listing in latest_by_source.values()],
        }
    )


@api_bp.get("/offers/<int:listing_id>")
def offers_for_listing(listing_id: int):
    listing = db.session.get(Listing, listing_id)
    if listing is None:
        return jsonify({"error": "not found"}), 404

    return jsonify(
        {
            "listing_id": listing.id,
            "source": listing.source,
            "selling_price": _num(listing.selling_price),
            "offers": [_serialize_offer(offer) for offer in listing.offers],
        }
    )


@api_bp.get("/price-history/<int:variant_id>")
def price_history(variant_id: int):
    variant = db.session.get(Variant, variant_id)
    if variant is None:
        return jsonify({"error": "not found"}), 404

    listings = Listing.query.filter_by(variant_id=variant_id).order_by(Listing.scraped_at.asc()).all()
    history = [
        {
            "listing_id": listing.id,
            "source": listing.source,
            "selling_price": _num(listing.selling_price),
            "mrp": _num(listing.mrp),
            "availability": listing.availability,
            "scraped_at": listing.scraped_at.isoformat() if listing.scraped_at else None,
            "crawl_id": listing.crawl_id,
        }
        for listing in listings
    ]

    return jsonify(
        {
            "variant_id": variant_id,
            "product": {"brand": variant.product.brand, "model": variant.product.model},
            "variant": {"storage": variant.storage, "colour": variant.colour},
            "history": history,
            # Only ever compares a source's own consecutive scrapes against
            # each other - never one source's price against another's.
            "price_drops": [asdict(drop) for drop in detect_price_drops(history)],
        }
    )
