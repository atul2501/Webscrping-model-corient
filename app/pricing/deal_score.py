"""A simple, documented 0-100 deal score used to break ties beyond raw
effective price - price weighs heaviest, with smaller nudges for discount
depth, stock availability, and source reliability.
"""

from dataclasses import dataclass

# Sources that have historically shown reliable/complete offer data get a
# small trust bump. Unknown sources default to a neutral weight.
SOURCE_RELIABILITY_WEIGHT = {
    "reliance_digital": 1.0,
    "vijay_sales": 1.0,
    "croma": 0.9,
}


@dataclass
class DealScoreInputs:
    effective_price: float
    lowest_effective_price_in_group: float
    highest_effective_price_in_group: float
    discount_percent: float
    availability: str | None
    source: str


def calculate_deal_score(inputs: DealScoreInputs) -> float:
    price_range = inputs.highest_effective_price_in_group - inputs.lowest_effective_price_in_group
    if price_range <= 0:
        price_score = 100.0
    else:
        position = (inputs.effective_price - inputs.lowest_effective_price_in_group) / price_range
        price_score = 100.0 * (1 - position)

    discount_score = min(inputs.discount_percent, 30.0) / 30.0 * 100.0

    availability_score = 100.0 if (inputs.availability or "").lower() in ("in_stock", "available") else 40.0

    reliability_weight = SOURCE_RELIABILITY_WEIGHT.get(inputs.source, 0.85)

    weighted = (price_score * 0.6 + discount_score * 0.2 + availability_score * 0.2) * reliability_weight
    return round(min(weighted, 100.0), 1)
