from unittest.mock import MagicMock

from app.matching.matcher import get_or_create_variant, prefetch_variants
from app.matching.normalizer import parse_product_name
from app.models import Variant


def test_get_or_create_variant_is_idempotent_for_exact_variant_key(app, db):
    parsed = parse_product_name("Apple iPhone 17 Pro (256GB Storage, Black)")
    v1 = get_or_create_variant(parsed)
    db.session.commit()
    v2 = get_or_create_variant(parse_product_name("Apple iPhone 17 Pro (256GB Storage, Black) P245195"))
    assert v1.id == v2.id


def test_fuzzy_fallback_does_not_over_merge_distinct_models(app, db):
    # "17 Pro" vs "17 Pro Max" are genuinely different phones, same brand and
    # storage - the fuzzy fallback's threshold must be strict enough that
    # this near-miss-looking pair is NOT collapsed into one variant.
    first = get_or_create_variant(parse_product_name("Apple iPhone 17 Pro (256GB Storage, Black)"))
    db.session.commit()
    second = get_or_create_variant(parse_product_name("Apple iPhone 17 Pro Max (256GB Storage, Black)"))
    db.session.commit()
    assert first.id != second.id


def test_different_colour_creates_separate_variant_not_fuzzy_merged(app, db):
    # Regression: the fuzzy fallback must not ignore colour just because the
    # model text is an exact match - "256GB Cosmic Orange" and "256GB
    # Silver" are different variants, not textual drift on the same one.
    orange = get_or_create_variant(parse_product_name("Apple iPhone 17 Pro (256GB Storage, Cosmic Orange)"))
    db.session.commit()
    silver = get_or_create_variant(parse_product_name("Apple iPhone 17 Pro (256GB Storage, Silver)"))
    db.session.commit()
    assert orange.id != silver.id
    assert orange.colour == "Cosmic Orange"
    assert silver.colour == "Silver"


def test_different_storage_creates_separate_variant(app, db):
    v256 = get_or_create_variant(parse_product_name("Apple iPhone 17 Pro (256GB Storage, Black)"))
    db.session.commit()
    v512 = get_or_create_variant(parse_product_name("Apple iPhone 17 Pro (512GB Storage, Black)"))
    db.session.commit()
    assert v256.id != v512.id
    assert v256.product_id == v512.product_id


def test_prefetch_variants_finds_existing_rows_by_key(app, db):
    parsed = parse_product_name("Apple iPhone 17 Pro (256GB Storage, Black)")
    created = get_or_create_variant(parsed)
    db.session.commit()

    prefetched = prefetch_variants([parsed.variant_key, "brand|missing|unknown|any"])
    assert prefetched == {parsed.variant_key: created}


def test_prefetch_variants_empty_input_does_not_query(app, db):
    assert prefetch_variants([]) == {}


def test_get_or_create_variant_uses_cache_hit_without_querying(app, db, monkeypatch):
    parsed = parse_product_name("Apple iPhone 17 Pro (256GB Storage, Black)")
    created = get_or_create_variant(parsed)
    db.session.commit()

    cache = {parsed.variant_key: created}

    # Variant.query is normally Flask-SQLAlchemy's _QueryProperty descriptor;
    # replacing it outright with a plain MagicMock means any access to
    # Variant.query (i.e. any attempt to run a query) raises, proving the
    # cache hit below is served without touching the DB at all.
    exploding_query = MagicMock()
    exploding_query.filter_by.side_effect = AssertionError("must not query the DB on a cache hit")
    monkeypatch.setattr(Variant, "query", exploding_query)

    assert get_or_create_variant(parsed, cache=cache) is created


def test_get_or_create_variant_writes_new_rows_back_into_cache(app, db):
    parsed = parse_product_name("Apple iPhone 17 Pro (256GB Storage, Black)")
    cache: dict = {}

    first = get_or_create_variant(parsed, cache=cache)
    db.session.commit()
    assert cache[parsed.variant_key] is first

    # A second, textually-identical listing in the same batch must reuse the
    # cached row rather than issuing another query or creating a duplicate.
    second = get_or_create_variant(parsed, cache=cache)
    assert second.id == first.id
