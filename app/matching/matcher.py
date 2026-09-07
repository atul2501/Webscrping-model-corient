"""Groups parsed listings into canonical Product/Variant rows so the same
phone from different retailers lands in one comparison group.

Strategy: an exact variant_key match (brand|model|storage|colour, all
normalized by normalizer.py) is used first. When a source's naming produces
a near-miss variant_key (e.g. an extra/missing word), a fuzzy fallback
compares the candidate's model text against existing variants that already
share the same brand and storage, using rapidfuzz - this catches drift in
model-name formatting without fracturing an otherwise-identical variant into
two rows.
"""

import logging

from rapidfuzz import fuzz

from app.extensions import db
from app.matching.normalizer import ParsedProduct
from app.models import Product, Variant

FUZZY_MATCH_THRESHOLD = 90

logger = logging.getLogger(__name__)


def _find_fuzzy_variant(parsed: ParsedProduct) -> Variant | None:
    # Storage and colour are exact-match filters, not part of the fuzzy
    # comparison: they're genuinely distinguishing attributes (256GB Cosmic
    # Orange is a different variant/SKU from 256GB Silver), not textual
    # drift. Only the model name text is fuzzy-compared, to catch things
    # like "17 Pro" vs "17Pro" without also merging different colours.
    candidates = (
        Variant.query.join(Product)
        .filter(
            Product.brand == parsed.brand,
            Variant.storage == parsed.storage,
            Variant.colour == parsed.colour,
        )
        .all()
    )
    if not candidates:
        return None

    best_variant, best_score = None, 0.0
    for candidate in candidates:
        candidate_model = candidate.product.model
        score = fuzz.token_sort_ratio(candidate_model.lower(), parsed.model.lower())
        if score > best_score:
            best_variant, best_score = candidate, score

    if best_variant is not None and best_score >= FUZZY_MATCH_THRESHOLD:
        logger.info(
            "Fuzzy-matched %r to existing variant %r (score=%.1f)",
            parsed.model,
            best_variant.product.model,
            best_score,
            extra={"source": "matcher"},
        )
        return best_variant
    return None


def prefetch_variants(variant_keys) -> dict[str, Variant]:
    """Bulk-load existing Variant rows for a batch of variant_keys in a
    single query. A caller persisting many listings at once (a live search's
    results, or a full-catalog crawl's hundreds) can pass the result here as
    `cache` to get_or_create_variant, turning what would otherwise be one
    exact-match query per listing into a single query for every listing
    whose product has already been seen before.
    """

    keys = {k for k in variant_keys if k}
    if not keys:
        return {}
    variants = Variant.query.filter(Variant.variant_key.in_(keys)).all()
    return {v.variant_key: v for v in variants}


def get_or_create_variant(parsed: ParsedProduct, cache: dict[str, Variant] | None = None) -> Variant:
    """Idempotently resolve a ParsedProduct to a Variant row, creating
    Product/Variant rows on first sight of a given brand/model/storage/colour.

    `cache` is an optional variant_key -> Variant map, typically the result
    of `prefetch_variants` for the whole batch this call is part of - an
    exact-key hit is served from it with no query, and any row this call
    resolves (fuzzy-matched or newly created) is written back into it so a
    later duplicate in the same batch also skips the query.
    """

    if cache is not None and parsed.variant_key in cache:
        return cache[parsed.variant_key]

    existing = Variant.query.filter_by(variant_key=parsed.variant_key).first()
    if existing is not None:
        if cache is not None:
            cache[parsed.variant_key] = existing
        return existing

    fuzzy_match = _find_fuzzy_variant(parsed)
    if fuzzy_match is not None:
        if cache is not None:
            cache[parsed.variant_key] = fuzzy_match
        return fuzzy_match

    product = Product.query.filter_by(brand=parsed.brand, model=parsed.model).first()
    if product is None:
        product = Product(brand=parsed.brand, model=parsed.model, canonical_name=f"{parsed.brand} {parsed.model}")
        db.session.add(product)
        db.session.flush()

    variant = Variant(
        product_id=product.id,
        storage=parsed.storage,
        colour=parsed.colour,
        variant_key=parsed.variant_key,
    )
    db.session.add(variant)
    db.session.flush()
    if cache is not None:
        cache[parsed.variant_key] = variant
    return variant
