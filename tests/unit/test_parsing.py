from app.scrapers.parsing import (
    extract_bank,
    fix_mangled_rupee_symbol,
    guess_offer_type,
    parse_price,
    text_matches_query,
)


def test_parse_price_strips_commas_and_currency_symbols():
    assert parse_price("Rs.1,29,900") == 129900.0
    assert parse_price("₹59,900") == 59900.0
    assert parse_price("69900.50") == 69900.5


def test_parse_price_returns_none_for_missing_or_unparseable_text():
    assert parse_price(None) is None
    assert parse_price("") is None
    assert parse_price("Out of stock") is None


def test_extract_bank_finds_known_bank_case_insensitively():
    assert extract_bank("10% off with hdfc bank cards") == "HDFC"
    assert extract_bank("No offer here") is None
    assert extract_bank(None) is None


def test_extract_bank_prefers_longer_match_over_shorter_substring():
    # "IndusInd Bank" and "IndusInd" are both in KNOWN_BANKS - the longer,
    # more specific name must win over a shorter one that's also a substring.
    assert extract_bank("10% off with IndusInd Bank cards") == "IndusInd Bank"


def test_guess_offer_type_classifies_no_cost_emi():
    assert guess_offer_type("No Cost EMI available") == "no_cost_emi"
    assert guess_offer_type("No-Cost EMI on select cards") == "no_cost_emi"


def test_guess_offer_type_classifies_plain_emi():
    assert guess_offer_type("EMI starting at Rs.2,000/month") == "emi"


def test_guess_offer_type_classifies_exchange():
    assert guess_offer_type("Get up to Rs.20,000 off on exchange") == "exchange"


def test_guess_offer_type_classifies_bank_vs_card():
    assert guess_offer_type("10% instant discount with HDFC Bank") == "bank"
    assert guess_offer_type("10% instant discount with HDFC Bank cards") == "card"


def test_guess_offer_type_falls_back_to_other():
    assert guess_offer_type("Limited period offer") == "other"
    assert guess_offer_type(None) == "other"


def test_text_matches_query_requires_every_significant_token():
    assert text_matches_query("Apple iPhone 15 (128GB, Blue)", "iPhone 15") is True
    assert text_matches_query("Apple iPhone 15 (128GB, Blue)", "iPhone 16") is False


def test_text_matches_query_empty_query_matches_anything():
    assert text_matches_query("Anything at all", "") is True


def test_fix_mangled_rupee_symbol_replaces_question_mark_before_digit():
    # Regression: confirmed live against Reliance Digital's raw HTTP response
    # bytes that their own authored offer copy contains a literal "?" where
    # a Rupee sign was clearly intended (present verbatim even in an
    # embedded CMS JSON config on the same page) - not a decoding bug on our
    # side. Only "?" immediately before a digit is rewritten.
    assert fix_mangled_rupee_symbol("?4K EMI Off or ?3K Full Swipe CC*") == "₹4K EMI Off or ₹3K Full Swipe CC*"


def test_fix_mangled_rupee_symbol_leaves_real_question_marks_alone():
    assert fix_mangled_rupee_symbol("Best deal on iPhone 15?") == "Best deal on iPhone 15?"
    assert fix_mangled_rupee_symbol("Is this a discount?") == "Is this a discount?"
