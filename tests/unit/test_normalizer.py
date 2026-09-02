"""Cases below mirror the real product-title shapes observed from the two
working live adapters (Vijay Sales' GraphQL search, Reliance Digital's
server-rendered listing cards): brand+model first, then a comma/paren
delimited spec list ending in colour, e.g.
"Apple iPhone 17 Pro (256GB Storage, Black)" or
"OPPO Reno16c 256 GB, 8 GB RAM, Stellar Purple, Mobile Phone".
"""

from app.matching.normalizer import parse_product_name


def test_parses_paren_delimited_title():
    parsed = parse_product_name("Apple iPhone 17 Pro (256GB Storage, Black)")
    assert parsed.brand == "Apple"
    # "iPhone" is kept in the model text (it reads as part of the model, not
    # just a brand signal) - only the redundant "Apple" company name is
    # stripped.
    assert parsed.model == "iPhone 17 Pro"
    assert parsed.storage == "256GB"
    assert parsed.storage_gb == 256
    assert parsed.colour == "Black"


def test_parses_comma_delimited_title_with_ram_and_filler_segments():
    parsed = parse_product_name("OPPO Reno16c 256 GB, 8 GB RAM, Stellar Purple, Mobile Phone")
    assert parsed.brand == "Oppo"
    assert "Reno" in parsed.model
    assert parsed.storage_gb == 256
    # RAM ("8 GB RAM") and filler ("Mobile Phone") segments must not be
    # mistaken for the colour - "Stellar Purple" is the real one.
    assert parsed.colour == "Stellar Purple"


def test_strips_trailing_sku_code_vijay_sales_appends_to_search_results():
    parsed = parse_product_name("Apple iPhone 17 (256GB Storage, White) P245180")
    assert parsed.colour == "White"
    assert "P245180" not in parsed.model


def test_tb_storage_normalizes_to_gb_equivalent():
    parsed = parse_product_name("Apple iPhone 17 Pro Max (1TB Storage, Cosmic Orange)")
    assert parsed.storage == "1TB"
    assert parsed.storage_gb == 1024


def test_colour_hint_overrides_free_text_extraction():
    parsed = parse_product_name("Apple iPhone 17 (256GB Storage, Black)", colour_hint="Ultra Marine")
    assert parsed.colour == "Ultramarine"


def test_model_suffix_letter_not_split_from_digit():
    # "17e" is a real Apple model name and must survive as one token, unlike
    # concatenated names like "iphone17pro" which do need splitting.
    parsed = parse_product_name("Apple iPhone 17e")
    assert parsed.model == "iPhone 17e"


def test_trailing_sku_with_no_preceding_space_is_still_stripped():
    # Real Vijay Sales quirk: some search results glue the SKU straight onto
    # the closing paren with no space, e.g. "...Black)P232288".
    parsed = parse_product_name("Apple iPhone 16 (128GB Storage, Black)P232288")
    assert parsed.colour == "Black"
    assert "P232288" not in parsed.model


def test_condensed_brand_model_is_still_split_on_boundaries():
    parsed = parse_product_name("iPhone17Pro")
    assert "17" in parsed.model.split()
    assert "Pro" in parsed.model.split()


def test_same_listing_from_two_sources_yields_same_variant_key():
    a = parse_product_name("Apple iPhone 17 Pro (256GB Storage, Cosmic Orange)")
    b = parse_product_name("Apple iPhone 17 Pro (256GB Storage, Cosmic Orange) P245195")
    assert a.variant_key == b.variant_key


def test_different_colour_yields_different_variant_key():
    black = parse_product_name("Apple iPhone 17 Pro (256GB Storage, Black)")
    silver = parse_product_name("Apple iPhone 17 Pro (256GB Storage, Silver)")
    assert black.variant_key != silver.variant_key


def test_unknown_brand_falls_back_gracefully():
    parsed = parse_product_name("SomeNewBrand Widget X1 (128GB Storage, Blue)")
    assert parsed.brand == "Unknown"
    assert parsed.storage_gb == 128
