"""Shared adapter contract. Every retailer adapter subclasses BaseAdapter and
implements only `search()` - session management, retries, rate limiting,
robots.txt checks, and turning any failure into a clean AdapterResult instead
of a raised exception are all handled once, here.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.utils import robots
from app.utils.http import DomainRateLimiter, FetchResult, build_session, fetch


class SourceBlockedError(Exception):
    """The source refused the request (403 / access control / bot protection)."""


class SourceFetchError(Exception):
    """A non-blocking fetch failure: timeout, connection error, 4xx/5xx, etc."""


@dataclass
class SearchQuery:
    model: str
    storage: str | None = None
    colour: str | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    # 1-indexed. Only VijaySalesAdapter can actually honour page > 1 (its
    # GraphQL search supports real pagination) - Croma/Reliance Digital fetch
    # a single fixed page per query and return no extra listings for page > 1
    # rather than re-returning (and duplicating) page 1's results.
    page: int = 1


@dataclass
class RawOffer:
    offer_text: str
    offer_type: str  # bank | card | exchange | no_cost_emi | other
    bank: str | None = None
    offer_discount: float | None = None
    emi_available: bool = False
    emi_tenure: int | None = None
    emi_rate: float | None = None
    valid_till_text: str | None = None


@dataclass
class RawListing:
    source: str
    product_name_raw: str
    sku: str | None = None
    product_url: str | None = None
    image_url: str | None = None
    currency: str = "INR"
    mrp: float | None = None
    selling_price: float | None = None
    discount: float | None = None
    availability: str | None = None
    seller: str | None = None
    rating: float | None = None
    review_count: int | None = None
    colour_hint: str | None = None
    storage_hint: str | None = None
    brand_hint: str | None = None
    offers: list[RawOffer] = field(default_factory=list)


@dataclass
class AdapterResult:
    source: str
    ok: bool
    listings: list[RawListing] = field(default_factory=list)
    error: str | None = None
    blocked: bool = False


class BaseAdapter(ABC):
    source_name: str
    domain: str
    user_agent_token: str = "PriceIntelBot"

    def __init__(self, config, rate_limiter: DomainRateLimiter | None = None):
        # `config` is Flask's app.config (dict-like), so this always uses
        # item access - never attribute access - to read settings from it.
        self.config = config
        self.session = build_session(max_retries=config["HTTP_MAX_RETRIES"])
        self.rate_limiter = rate_limiter or DomainRateLimiter(config["RATE_LIMIT_SECONDS_PER_DOMAIN"])
        self.logger = logging.getLogger(f"scraper.{self.source_name}")

    def run(self, query: SearchQuery, crawl_id: str) -> AdapterResult:
        extra = {"crawl_id": crawl_id, "source": self.source_name}
        try:
            listings = self.search(query, crawl_id)
            self.logger.info("adapter completed: %d listing(s)", len(listings), extra=extra)
            return AdapterResult(source=self.source_name, ok=True, listings=listings)
        except SourceBlockedError as exc:
            self.logger.warning("adapter blocked by source: %s", exc, extra=extra)
            return AdapterResult(source=self.source_name, ok=False, error=str(exc), blocked=True)
        except SourceFetchError as exc:
            self.logger.warning("adapter fetch failed: %s", exc, extra=extra)
            return AdapterResult(source=self.source_name, ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - a source failure must never crash the app
            self.logger.exception("adapter raised an unexpected error", extra=extra)
            return AdapterResult(source=self.source_name, ok=False, error=f"unexpected error: {exc}")

    @abstractmethod
    def search(self, query: SearchQuery, crawl_id: str) -> list[RawListing]:
        """Return listings for the query. Raise SourceBlockedError /
        SourceFetchError / anything - run() converts it to AdapterResult."""

    def get(self, url: str, *, params: dict | None = None, crawl_id: str = "") -> FetchResult:
        if not robots.is_allowed(url, self.user_agent_token):
            raise SourceBlockedError(f"Disallowed by robots.txt: {url}")

        result = fetch(
            self.session,
            url,
            timeout=self.config["HTTP_TIMEOUT_SECONDS"],
            rate_limiter=self.rate_limiter,
            domain=self.domain,
            params=params,
        )
        self.logger.info(
            "fetched %s -> %s (%.0fms)",
            url,
            result.status_code,
            result.elapsed_ms,
            extra={"crawl_id": crawl_id, "source": self.source_name, "url": url, "status_code": result.status_code},
        )
        if not result.ok:
            if result.blocked:
                raise SourceBlockedError(result.error or f"blocked fetching {url}")
            raise SourceFetchError(result.error or f"failed fetching {url}")
        return result
