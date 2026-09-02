"""Small parsing helpers shared by every adapter: currency strings -> floats,
bank-name detection in free-text offer copy, and query/listing text matching.
"""

import re

_PRICE_RE = re.compile(r"[\d,]+(?:\.\d+)?")

KNOWN_BANKS = [
    "HDFC", "ICICI", "SBI", "Axis", "Kotak", "IDFC", "Yes Bank", "RBL",
    "PNB", "IndusInd", "HSBC", "Federal Bank", "AU Small Finance",
    "Standard Chartered", "Citi", "Bank of Baroda", "IDBI", "OneCard",
    "American Express", "Amex", "IndusInd Bank",
]

_BANKS_BY_LENGTH = sorted(KNOWN_BANKS, key=len, reverse=True)


def parse_price(text: str | None) -> float | None:
    if not text:
        return None
    match = _PRICE_RE.search(text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def extract_bank(text: str | None) -> str | None:
    if not text:
        return None
    for bank in _BANKS_BY_LENGTH:
        if bank.lower() in text.lower():
            return bank
    return None


def guess_offer_type(text: str | None) -> str:
    if not text:
        return "other"
    lowered = text.lower()
    if "no cost emi" in lowered or "no-cost emi" in lowered:
        return "no_cost_emi"
    if "emi" in lowered:
        return "emi"
    if "exchange" in lowered:
        return "exchange"
    if extract_bank(text):
        return "bank" if "card" not in lowered else "card"
    return "other"


def _significant_tokens(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in tokens if len(t) > 1 or t.isdigit()]


def text_matches_query(candidate_text: str, query_model: str) -> bool:
    """True if every significant token of the query appears in the candidate
    text - a conservative substring match used to filter a category listing
    down to the requested model without needing a (possibly robots.txt
    disallowed) site search endpoint.
    """

    candidate_tokens = set(_significant_tokens(candidate_text))
    query_tokens = _significant_tokens(query_model)
    if not query_tokens:
        return True
    return all(token in candidate_tokens for token in query_tokens)
