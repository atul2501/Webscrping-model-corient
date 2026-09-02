from app.matching.matcher import get_or_create_variant
from app.matching.normalizer import parse_product_name


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
