"""Croma adapter.

Direct verification during development showed croma.com returning HTTP 403
("Access Denied", Akamai edge WAF - see tests/fixtures/croma_403.html for the
real captured response body) for *every* path tried from this environment,
including the homepage and /robots.txt itself, not just the target listing
page. That is bot-management infrastructure making an access-control
decision, not a robots.txt rule - per the spec's explicit instruction not to
bypass access controls, this adapter does not attempt stealth headers,
proxy rotation, or any other evasion to get around it.

The selectors below are written from Croma's publicly documented page
structure/conventions but are UNVERIFIED against live markup, since no
successful fetch was obtainable to confirm them while building this. They
are intentionally written defensively (multiple candidate selectors, skip
rather than crash on a miss) so that on a network where Croma is reachable
(e.g. most residential/non-datacenter IPs) this adapter has a real chance of
working, and on a network where it is not, it fails the way the rest of this
system is designed to handle a source failing: gracefully, via
SourceBlockedError, leaving the other adapters' results intact.
"""

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.scrapers.base import BaseAdapter, RawListing, RawOffer, SearchQuery
from app.scrapers.parsing import extract_bank, guess_offer_type, parse_price, text_matches_query

BASE_URL = "https://www.croma.com"
LISTING_URL = f"{BASE_URL}/phoneswearables/mobile-phones/apple-iphones/c/97"

# Candidate selectors, tried in order - Croma's markup has changed naming
# schemes across redesigns (cro-product-list, plp-card, product-item...).
CARD_SELECTORS = ["li.product-item", "div.cro-product-list", "div.plp-card", "li.plp-product"]
TITLE_SELECTORS = ["h3.product-title", ".product-title", "h3", ".plp-card__title"]
LINK_SELECTORS = ["a.product-item-link", "a"]
IMAGE_SELECTORS = ["img.product-img", "img"]
PRICE_SELECTORS = [".amount", ".new-price", ".plp-card__price", ".cp-price"]
MRP_SELECTORS = [".old-price", ".mrp", ".plp-card__mrp"]
OFFER_SELECTORS = [".offer-text", ".plp-card__offer", ".cp-offer"]


def _first_match(node, selectors: list[str]):
    for selector in selectors:
        found = node.select_one(selector)
        if found is not None:
            return found
    return None


class CromaAdapter(BaseAdapter):
    source_name = "croma"
    domain = "www.croma.com"

    def search(self, query: SearchQuery, crawl_id: str) -> list[RawListing]:
        result = self.get(LISTING_URL, crawl_id=crawl_id)
        soup = BeautifulSoup(result.text, "lxml")

        cards = []
        for selector in CARD_SELECTORS:
            cards = soup.select(selector)
            if cards:
                break

        listings: list[RawListing] = []
        for card in cards:
            listing = self._parse_card(card)
            if listing is not None and text_matches_query(listing.product_name_raw, query.model):
                listings.append(listing)

        return listings

    def _parse_card(self, card) -> RawListing | None:
        title_el = _first_match(card, TITLE_SELECTORS)
        if title_el is None:
            return None
        name = title_el.get_text(strip=True)
        if not name:
            return None

        link_el = _first_match(card, LINK_SELECTORS)
        product_url = None
        if link_el is not None and link_el.get("href"):
            product_url = urljoin(BASE_URL, link_el["href"].split("?")[0])

        image_el = _first_match(card, IMAGE_SELECTORS)
        image_url = image_el.get("src") or image_el.get("data-src") if image_el is not None else None

        price_el = _first_match(card, PRICE_SELECTORS)
        selling_price = parse_price(price_el.get_text(strip=True)) if price_el is not None else None

        mrp_el = _first_match(card, MRP_SELECTORS)
        mrp = parse_price(mrp_el.get_text(strip=True)) if mrp_el is not None else selling_price

        discount = round(mrp - selling_price, 2) if mrp is not None and selling_price is not None else None

        offers: list[RawOffer] = []
        offer_el = _first_match(card, OFFER_SELECTORS)
        if offer_el is not None:
            text = offer_el.get_text(strip=True)
            if text:
                offers.append(
                    RawOffer(
                        offer_text=text,
                        offer_type=guess_offer_type(text),
                        bank=extract_bank(text),
                        emi_available="emi" in text.lower(),
                    )
                )

        return RawListing(
            source=self.source_name,
            product_name_raw=name,
            product_url=product_url,
            image_url=image_url,
            currency="INR",
            mrp=mrp,
            selling_price=selling_price,
            discount=discount,
            availability="available",
            seller="Croma",
            offers=offers,
        )
