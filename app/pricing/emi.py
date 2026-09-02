"""EMI and effective-price calculations.

Everything here is a *calculated estimate* derived from scraped facts
(selling_price, offer_discount, ...) - never itself stored as a scraped
fact, per the spec's requirement to keep scraped data and derived values
separate and to label derived values as estimates.
"""

from dataclasses import dataclass, field


@dataclass
class EmiScenario:
    principal_financed: float
    tenure_months: int
    annual_rate_percent: float
    monthly_emi: float
    total_repayment: float
    total_interest: float
    is_no_cost_emi: bool
    estimate: bool = field(default=True)


def calculate_emi(
    financed_amount: float,
    tenure_months: int,
    annual_rate_percent: float,
    *,
    no_cost_emi: bool = False,
) -> EmiScenario:
    """Reducing-balance EMI, or a flat no-cost-EMI split when the source
    explicitly advertises a no-cost EMI offer (principal spread evenly over
    the tenure with no added interest - a common, clearly-labelled assumption
    for how sellers price "no cost EMI" schemes).
    """

    if tenure_months <= 0:
        raise ValueError("tenure_months must be positive")
    if financed_amount < 0:
        raise ValueError("financed_amount cannot be negative")

    if no_cost_emi or annual_rate_percent <= 0:
        monthly_emi = financed_amount / tenure_months
        rate_used = 0.0
    else:
        monthly_rate = annual_rate_percent / 12 / 100
        growth = (1 + monthly_rate) ** tenure_months
        monthly_emi = financed_amount * monthly_rate * growth / (growth - 1)
        rate_used = annual_rate_percent

    total_repayment = monthly_emi * tenure_months
    total_interest = total_repayment - financed_amount

    return EmiScenario(
        principal_financed=round(financed_amount, 2),
        tenure_months=tenure_months,
        annual_rate_percent=rate_used,
        monthly_emi=round(monthly_emi, 2),
        total_repayment=round(total_repayment, 2),
        total_interest=round(max(total_interest, 0.0), 2),
        is_no_cost_emi=bool(no_cost_emi or annual_rate_percent <= 0),
    )


def best_offer_discount(offer_discounts: list[float]) -> float:
    """Offer facts are not assumed combinable (per spec) - use the single
    best (largest) discount rather than summing every offer.
    """

    return max(offer_discounts) if offer_discounts else 0.0


def effective_price(selling_price: float, offer_discounts: list[float]) -> float:
    discount = best_offer_discount(offer_discounts)
    return round(max(selling_price - discount, 0.0), 2)
