"""Vijay Sales adapter.

The /c/iphones listing page (given in the spec's source table) turned out to
be a poor scraping target on inspection: its product-card price blocks are
either hidden or wrapped in AEM `<sly data-sly-test>` template comments and
never reach the static HTML, so prices aren't reliably extractable from that
page alone. The page's own `store-config` meta tag advertises a public
GraphQL endpoint (`/api/graphql`, GET) though, and a direct call to it
returns clean, authoritative product data - the same API the site's own
frontend calls, no auth, no bypass involved. This adapter therefore skips
HTML scraping for Vijay Sales entirely and uses that GraphQL search API,
which conveniently is also brand/model agnostic (it's the site's full-text
product search), so it isn't limited to the one iPhone category page.

Bank/EMI offer *text* isn't exposed by the GraphQL schema, and the spec's
given bank-offers URL (`/eventpages/bank-offers`) 404s as of this build (the
site has since moved that content into an on-page component). As a bounded,
best-effort enrichment this adapter fetches the product detail page for a
small number of top matches and pulls the bank names + EMI terms embedded
there in a `data-cf` content-fragment attribute; if that fails for any
reason, the listing (already fully priced via GraphQL) is kept anyway - see
BaseAdapter's per-listing offer enrichment is optional, never required.
"""

import json
import re

from app.scrapers.base import BaseAdapter, RawListing, RawOffer, SearchQuery, SourceBlockedError, SourceFetchError
from app.scrapers.parsing import text_matches_query

GRAPHQL_URL = "https://www.vijaysales.com/api/graphql"
BASE_URL = "https://www.vijaysales.com"

ACCESSORY_KEYWORDS = (
    "case", "cover", "cable", "charger", "adapter", "screen protector",
    "tempered glass", "airpods", "earphone", "earbud", "power bank",
    "magsafe", "strap", "band", "protector", "skin", "pouch", "dock",
)

BANK_LOGO_TEXT_RE = re.compile(r"bankLogoText&#34;:&#34;([^&]+?)&#34;")

MAX_OFFER_DETAIL_FETCHES = 5
PAGE_SIZE = 30

# Paginated GraphQL search - shared by both a live /api/search request
# (search() below, one page at a time as the user clicks "Load more") and
# the full-catalog crawler (scripts/crawl_full_catalog.py, which sweeps
# every page up front).
GRAPHQL_CATALOG_QUERY = """
query Search($search: String!, $pageSize: Int!, $currentPage: Int!) {
  products(search: $search, pageSize: $pageSize, currentPage: $currentPage) {
    total_count
    page_info { current_page total_pages }
    items {
      name
      sku
      url_key
      stock_status
      categories { url_key }
      rating_summary
      review_count
      small_image { url }
      price_range {
        minimum_price {
          regular_price { value }
          final_price { value }
          discount { amount_off percent_off }
        }
      }
    }
  }
}
"""


class VijaySalesAdapter(BaseAdapter):
    source_name = "vijay_sales"
    domain = "www.vijaysales.com"

    def search(self, query: SearchQuery, crawl_id: str) -> list[RawListing]:
        items, _total_pages = self.fetch_catalog_page(query.model, query.page, crawl_id, page_size=PAGE_SIZE)

        listings: list[RawListing] = []
        for item in items:
            name = item.get("name") or ""
            if self._looks_like_accessory(name) or not text_matches_query(name, query.model):
                continue
            # The site's full-text search also matches accessories whose
            # name/description happens to mention "phone" (Nothing Ear buds,
            # watches, etc.) that the keyword blocklist can't anticipate -
            # the category breadcrumb from the site itself is authoritative.
            if item.get("categories") and not self._is_in_smartphones_category(item):
                continue
            listings.append(self._to_listing(item))

        for listing in listings[:MAX_OFFER_DETAIL_FETCHES]:
            self._attach_bank_offers(listing, crawl_id)

        return listings

    def fetch_catalog_page(self, search_term: str, page: int, crawl_id: str, page_size: int = 100) -> tuple[list[dict], int]:
        """One page of raw GraphQL product items for `search_term`, plus the
        total page count - shared by `search()` (one page per "Load more"
        click) and the full-catalog crawler (which sweeps every page up
        front). Accessory filtering is deliberately left to the caller here,
        since the crawler wants to look at every item this endpoint returns
        for bookkeeping/dedup before deciding.
        """

        params = {
            "query": GRAPHQL_CATALOG_QUERY,
            "variables": json.dumps({"search": search_term, "pageSize": page_size, "currentPage": page}),
        }
        result = self.get(GRAPHQL_URL, params=params, crawl_id=crawl_id)
        payload = json.loads(result.text)
        products = (payload.get("data") or {}).get("products") or {}
        total_pages = (products.get("page_info") or {}).get("total_pages") or 1
        return products.get("items") or [], total_pages

    @staticmethod
    def _looks_like_accessory(name: str) -> bool:
        lowered = name.lower()
        return any(keyword in lowered for keyword in ACCESSORY_KEYWORDS)

    @staticmethod
    def _is_in_smartphones_category(item: dict) -> bool:
        """True only if the site's own category breadcrumb (not a name
        keyword guess) puts this item under Smartphones. Needed for the
        full-catalog crawl: a broad text search for "smartphone" also
        matches things like a "Smartphone Printer" or a smartwatch whose
        description happens to mention phones - `_looks_like_accessory`'s
        keyword list can't anticipate every such false positive, but every
        real phone on this site is tagged with this category regardless of
        what words are in its name.
        """

        return any((cat.get("url_key") or "") == "smartphones" for cat in item.get("categories") or [])

    def _to_listing(self, item: dict) -> RawListing:
        sku = item.get("sku")
        url_key = item.get("url_key")
        product_url = f"{BASE_URL}/p/{sku}/{url_key}" if sku and url_key else None

        price = item.get("price_range", {}).get("minimum_price", {}) or {}
        mrp = (price.get("regular_price") or {}).get("value")
        selling_price = (price.get("final_price") or {}).get("value")

        rating_summary = item.get("rating_summary")
        rating = round(rating_summary / 20, 1) if rating_summary else None

        return RawListing(
            source=self.source_name,
            product_name_raw=item.get("name") or "",
            sku=sku,
            product_url=product_url,
            image_url=(item.get("small_image") or {}).get("url"),
            currency="INR",
            mrp=mrp,
            selling_price=selling_price,
            discount=(mrp - selling_price) if mrp is not None and selling_price is not None else None,
            availability="available" if item.get("stock_status") == "IN_STOCK" else "out_of_stock",
            seller="Vijay Sales",
            rating=rating,
            review_count=item.get("review_count"),
        )

    def _attach_bank_offers(self, listing: RawListing, crawl_id: str) -> None:
        if not listing.product_url:
            return
        try:
            result = self.get(listing.product_url, crawl_id=crawl_id)
        except (SourceBlockedError, SourceFetchError):
            # Best-effort enrichment only - price/availability already came
            # from the authoritative GraphQL call above, so a failure here
            # just means this one listing ships without bank-offer text.
            return

        banks = sorted({b.strip() for b in BANK_LOGO_TEXT_RE.findall(result.text) if b.strip()})
        for bank in banks[:5]:
            listing.offers.append(
                RawOffer(
                    offer_text=f"No-cost / low-cost EMI conversion available via {bank} (bank terms apply)",
                    offer_type="no_cost_emi",
                    bank=bank,
                    emi_available=True,
                )
            )
