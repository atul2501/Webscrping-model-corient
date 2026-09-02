import pytest

from app.pricing.emi import best_offer_discount, calculate_emi, effective_price


def test_reducing_balance_emi_matches_known_value():
    # Textbook check: P=100000, annual rate=12%, n=12 months -> EMI ~= 8884.88
    scenario = calculate_emi(100000, 12, 12.0)
    assert scenario.monthly_emi == pytest.approx(8884.88, abs=0.5)
    assert scenario.is_no_cost_emi is False
    assert scenario.estimate is True
    assert scenario.total_repayment == pytest.approx(scenario.monthly_emi * 12, abs=0.01)


def test_no_cost_emi_splits_principal_evenly_with_zero_interest():
    scenario = calculate_emi(120000, 12, 14.0, no_cost_emi=True)
    assert scenario.monthly_emi == pytest.approx(10000.0, abs=0.01)
    assert scenario.total_interest == 0.0
    assert scenario.is_no_cost_emi is True


def test_zero_rate_behaves_like_no_cost_emi():
    scenario = calculate_emi(60000, 6, 0.0)
    assert scenario.monthly_emi == pytest.approx(10000.0, abs=0.01)
    assert scenario.is_no_cost_emi is True


def test_rejects_non_positive_tenure():
    with pytest.raises(ValueError):
        calculate_emi(50000, 0, 12.0)


def test_rejects_negative_financed_amount():
    with pytest.raises(ValueError):
        calculate_emi(-100, 12, 12.0)


def test_best_offer_discount_is_not_a_sum_of_all_offers():
    # Spec: don't assume every discount is combinable - use the single best one.
    assert best_offer_discount([1000, 4000, 2500]) == 4000
    assert best_offer_discount([]) == 0.0


def test_effective_price_applies_only_the_best_discount():
    assert effective_price(100000, [1000, 4000]) == 96000.0


def test_effective_price_never_goes_negative():
    assert effective_price(1000, [5000]) == 0.0
