from app.data.model_catalog import get_model_options, suggest_models


def test_prefix_matches_rank_before_substring_matches():
    results = suggest_models("iphone 16")
    assert results[0].lower().startswith("iphone 16")


def test_case_insensitive():
    assert suggest_models("IPHONE 17 PRO") == suggest_models("iphone 17 pro")


def test_empty_query_returns_a_default_list_not_empty():
    assert len(suggest_models("")) > 0


def test_respects_limit():
    assert len(suggest_models("i", limit=3)) <= 3


def test_no_match_returns_empty_list():
    assert suggest_models("some totally made up phone name xyz123") == []


def test_model_options_exact_catalog_hit():
    options = get_model_options("iPhone 16")
    assert "128GB" in options["storage"]
    assert "Ultramarine" in options["colour"]


def test_model_options_case_insensitive_and_trims_whitespace():
    assert get_model_options("  iphone 16  ") == get_model_options("iPhone 16")


def test_model_options_partial_match_still_finds_family():
    # A query with extra words (e.g. what a user types with storage baked
    # in) should still resolve to the right model family.
    options = get_model_options("iPhone 16 Pro 256GB")
    assert "Natural Titanium" in options["colour"]


def test_model_options_unknown_model_falls_back_to_generic():
    options = get_model_options("Some Totally Unknown Phone 9000")
    assert options["storage"]
    assert options["colour"]


def test_model_options_empty_query_returns_generic():
    options = get_model_options("")
    assert options["storage"]
    assert options["colour"]
