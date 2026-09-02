"""Price-drop detection over a variant's scrape history.

Kept separate from EMI/deal-score (same principle as both: derived from
scraped facts, never itself a scraped fact) - compares each source's most
recent two scrapes independently, since prices across *different* sources
aren't a "drop", they're just different retailers.
"""

from dataclasses import dataclass


@dataclass
class PriceDrop:
    source: str
    previous_price: float
    current_price: float
    drop_amount: float
    drop_percent: float
    previous_scraped_at: str | None
    current_scraped_at: str | None


def detect_price_drops(history: list[dict]) -> list[PriceDrop]:
    """history: chronologically-ascending {source, selling_price, scraped_at}
    dicts, as returned by GET /api/price-history. A drop is only reported
    for a source with at least two priced scrapes where the latest is
    strictly below the one before it - a single scrape, or a flat/rising
    price, isn't a drop.
    """

    by_source: dict[str, list[dict]] = {}
    for point in history:
        if point.get("selling_price") is None:
            continue
        by_source.setdefault(point["source"], []).append(point)

    drops = []
    for source, points in by_source.items():
        if len(points) < 2:
            continue
        previous, current = points[-2], points[-1]
        if current["selling_price"] >= previous["selling_price"]:
            continue
        drop_amount = previous["selling_price"] - current["selling_price"]
        drop_percent = (drop_amount / previous["selling_price"]) * 100 if previous["selling_price"] else 0.0
        drops.append(
            PriceDrop(
                source=source,
                previous_price=previous["selling_price"],
                current_price=current["selling_price"],
                drop_amount=round(drop_amount, 2),
                drop_percent=round(drop_percent, 2),
                previous_scraped_at=previous["scraped_at"],
                current_scraped_at=current["scraped_at"],
            )
        )
    return drops
