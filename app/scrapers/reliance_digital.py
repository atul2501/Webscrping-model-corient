"""Reliance Digital adapter.

The spec's given /collection/smartphones listing page is fully
server-rendered (real product-card divs with name/price/MRP/discount/
image/link already in the raw HTML - no JS execution needed), but it only
ever shows the ~50 products (across *every* brand) that happen to be first
server-rendered right now - there's no pagination available within
robots.txt (see below), so a specific, less-common model can be entirely
absent from it. Verified during development: searching "iPhone 17 Pro"
against that page alone returned zero Reliance Digital results even though
the phone was very much in stock on the site.

Reliance Digital's own public sitemap
(sitemap.xml -> sitemap/collections.sitemap.xml) lists thousands of static,
robots-compliant /collection/<slug> pages, several of which are genuine,
complete per-model or per-brand catalogues - e.g. /collection/iphone-17-pro
lists every storage/colour combination of both iPhone 17 Pro *and* Pro Max,
and /collection/samsung-smartphones covers the current Samsung lineup. This
adapter tries the most specific known slug for the query first, then a
broader same-brand collection, then always falls back to the original
generic page - whichever tier actually returns matching listings wins.

These per-model slugs are Reliance Digital's own marketing/campaign URLs
though, not a documented stable API - some already 404 or redirect to an
empty page even among the ones checked while building this (their campaign
pages appear to rotate/expire over time). So this is a best-effort cascade,
not a hard dependency: a stale slug is skipped (not treated as a fetch
failure) and the adapter just falls through to the next tier, ultimately
never doing worse than the original single-page behaviour.

robots.txt disallows *every* URL containing a query string
(`Disallow: /*?*`, plus an explicit `Disallow: /products?q=*`), which is
exactly why none of this uses query-string pagination or search params -
every URL here, including the sitemap-discovered ones, is a static path.
Product URLs always get their `?internal_source=...` tracking suffix
stripped before being followed, for the same reason.
"""

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.scrapers.base import BaseAdapter, RawListing, RawOffer, SearchQuery, SourceBlockedError, SourceFetchError
from app.scrapers.parsing import extract_bank, guess_offer_type, parse_price, text_matches_query

BASE_URL = "https://www.reliancedigital.in"
GENERIC_LISTING_URL = f"{BASE_URL}/collection/smartphones"

# Verified against Reliance Digital's own sitemap/collections.sitemap.xml
# while building this - checked longest/most-specific keyword first, so
# "iphone 17 pro" is matched before the broader "iphone 17".
MODEL_COLLECTION_SLUGS: list[tuple[str, str]] = [
    ("iphone 17 pro", "iphone-17-pro"),
    ("iphone 17", "iphone-17"),
    ("iphone 16 plus", "iphone-16plus"),
    ("iphone 16e", "iphone-16e"),
    ("iphone 15", "iphone-15-range"),
    ("iphone 14", "iphone-14-mobiles"),
]

# Broader, brand-wide fallback collections - tried after a specific model
# slug misses (or when there isn't one), before falling all the way back to
# the fully generic, all-brands page. Not every brand has a working one -
# e.g. Nokia/Motorola/Itel's "-mobiles" collection pages return 200 but
# render their product grid client-side (no cards in the static HTML this
# adapter fetches), so they're deliberately left out here rather than added
# as dead weight - an untried/unlisted brand just skips straight to the
# generic page. Vivo/Oppo/Redmi/Jio's "-mobiles" pages, by contrast, are
# genuinely server-rendered with real product cards - verified live.
BRAND_FALLBACK_SLUGS: list[tuple[str, str]] = [
    ("iphone", "apple-smartphones"),
    ("apple", "apple-smartphones"),
    ("samsung", "samsung-smartphones"),
    ("galaxy", "samsung-smartphones"),
    ("oneplus", "oneplus-smartphones"),
    ("realme", "realme-smartphones"),
    ("vivo", "vivo-mobiles"),
    ("oppo", "oppo-mobiles"),
    ("redmi", "redmi-mobiles"),
    ("xiaomi", "redmi-mobiles"),
    ("jio", "jio-mobiles"),
]

# Every collection slug this adapter knows about, for the full-catalog
# crawler (scripts/crawl_full_catalog.py) to sweep - not used by a normal
# per-query search, which only ever needs the couple of tiers relevant to
# that one query.
ALL_CATALOG_COLLECTION_SLUGS: list[str] = list(
    dict.fromkeys(
        [slug for _, slug in MODEL_COLLECTION_SLUGS]
        + [slug for _, slug in BRAND_FALLBACK_SLUGS]
        + ["samsung-galaxy-mobiles", "apple-mobiles"]
    )
)


def _candidate_urls(model_query: str) -> list[str]:
    """Ordered, most-specific-first list of pages worth trying for this
    query - the caller stops at the first one that yields real matches.
    """

    lowered = model_query.lower()
    urls = []
    for keyword, slug in MODEL_COLLECTION_SLUGS:
        if keyword in lowered:
            urls.append(f"{BASE_URL}/collection/{slug}")
            break
    for keyword, slug in BRAND_FALLBACK_SLUGS:
        if keyword in lowered:
            urls.append(f"{BASE_URL}/collection/{slug}")
            break
    urls.append(GENERIC_LISTING_URL)
    return urls


class RelianceDigitalAdapter(BaseAdapter):
    source_name = "reliance_digital"
    domain = "www.reliancedigital.in"

    def search(self, query: SearchQuery, crawl_id: str) -> list[RawListing]:
        if query.page > 1:
            # Every tier here is a single static page - there's no query-
            # string pagination to follow (robots.txt disallows it outright,
            # see the module docstring), so a page > 1 request would just
            # re-fetch and re-return the exact same listings page 1 already
            # gave. Returning nothing lets "Load more" correctly treat this
            # source as exhausted after page 1 instead of duplicating rows.
            return []

        last_error: Exception | None = None
        any_tier_succeeded = False
        for url in _candidate_urls(query.model):
            try:
                listings = self._search_page(url, query, crawl_id)
            except (SourceBlockedError, SourceFetchError) as exc:
                # A stale/expired campaign slug (404, or blocked) shouldn't
                # sink the whole adapter - just try the next, less specific
                # tier. Only surfaced if every tier, including the generic
                # page, fails the same way.
                last_error = exc
                continue
            any_tier_succeeded = True
            if listings:
                return listings
        if not any_tier_succeeded and last_error is not None:
            raise last_error
        return []

    def _search_page(self, url: str, query: SearchQuery, crawl_id: str) -> list[RawListing]:
        result = self.get(url, crawl_id=crawl_id)
        soup = BeautifulSoup(result.text, "lxml")

        listings: list[RawListing] = []
        for card in soup.select("div.product-card"):
            listing = self._parse_card(card)
            if listing is None:
                continue
            if text_matches_query(listing.product_name_raw, query.model):
                listings.append(listing)

        return listings

    def _parse_card(self, card) -> RawListing | None:
        title_el = card.select_one(".product-card-title")
        if title_el is None:
            return None
        name = title_el.get_text(strip=True)

        link_el = card.select_one("a.product-card-image") or card.select_one("a.details-container")
        product_url = None
        if link_el is not None and link_el.get("href"):
            product_url = urljoin(BASE_URL, link_el["href"].split("?")[0])

        img_el = card.select_one("picture img")
        image_url = img_el.get("src") if img_el is not None else None

        selling_price = parse_price((card.select_one(".price-container .price") or {}).get_text(strip=True)
                                     if card.select_one(".price-container .price") else None)
        mrp_el = card.select_one(".mrp-amount")
        mrp = parse_price(mrp_el.get_text(strip=True)) if mrp_el else selling_price

        discount = None
        if mrp is not None and selling_price is not None:
            discount = round(mrp - selling_price, 2)

        out_of_stock = card.select_one(".out-of-stock") is not None
        availability = "out_of_stock" if out_of_stock else "available"

        sku = None
        if product_url:
            # Reliance Digital product slugs end in -<sku>, e.g. .../mff5yc-9388032
            tail = product_url.rstrip("/").split("-")[-1]
            sku = tail if tail.isdigit() else None

        offers: list[RawOffer] = []

        teaser_el = card.select_one(".teaser-tag")
        if teaser_el is not None:
            text = teaser_el.get_text(strip=True)
            if text:
                offers.append(
                    RawOffer(
                        offer_text=text,
                        offer_type=guess_offer_type(text),
                        bank=extract_bank(text),
                        emi_available="emi" in text.lower(),
                    )
                )

        best_price_el = card.select_one(".rolling-best-price[aria-label]")
        if best_price_el is not None and selling_price is not None:
            best_price = parse_price(best_price_el.get("aria-label"))
            if best_price is not None and best_price < selling_price:
                offers.append(
                    RawOffer(
                        offer_text=f"Best price with all applicable offers: Rs.{best_price:,.0f}",
                        offer_type="other",
                        offer_discount=round(selling_price - best_price, 2),
                    )
                )

        return RawListing(
            source=self.source_name,
            product_name_raw=name,
            sku=sku,
            product_url=product_url,
            image_url=image_url,
            currency="INR",
            mrp=mrp,
            selling_price=selling_price,
            discount=discount,
            availability=availability,
            seller="Reliance Digital",
            offers=offers,
        )
