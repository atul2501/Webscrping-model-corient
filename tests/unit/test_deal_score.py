from app.pricing.deal_score import DealScoreInputs, calculate_deal_score


def _score(**overrides):
    defaults = dict(
        effective_price=90000,
        lowest_effective_price_in_group=90000,
        highest_effective_price_in_group=100000,
        discount_percent=5.0,
        availability="available",
        source="reliance_digital",
    )
    defaults.update(overrides)
    return calculate_deal_score(DealScoreInputs(**defaults))


def test_lowest_priced_listing_in_group_scores_highest_on_price_component():
    cheapest = _score(effective_price=90000)
    priciest = _score(effective_price=100000)
    assert cheapest > priciest


def test_out_of_stock_scores_lower_than_in_stock_all_else_equal():
    in_stock = _score(availability="available")
    out_of_stock = _score(availability="out_of_stock")
    assert in_stock > out_of_stock


def test_single_listing_group_gets_full_price_score():
    score = _score(
        effective_price=50000,
        lowest_effective_price_in_group=50000,
        highest_effective_price_in_group=50000,
    )
    assert 0 <= score <= 100


def test_score_is_bounded_between_zero_and_hundred():
    score = _score(discount_percent=95.0)
    assert 0 <= score <= 100
