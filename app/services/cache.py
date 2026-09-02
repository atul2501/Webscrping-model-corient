"""DB-backed short-TTL cache so repeating the same search within a session
doesn't trigger a fresh scrape of every source (per the spec's requirement
to avoid unnecessary repeated requests).
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import SearchCache


def query_hash(query_dict: dict) -> str:
    normalized = json.dumps(query_dict, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _as_utc(dt: datetime) -> datetime:
    # SQLite drops tzinfo on round-trip even for DateTime(timezone=True)
    # columns (values are always written as UTC), so a naive value read back
    # from it is re-attached to UTC rather than compared against an aware
    # "now" and blowing up. Postgres preserves tzinfo, so this is a no-op there.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def get_cached_crawl_id(query_dict: dict, ttl_seconds: int) -> str | None:
    if ttl_seconds <= 0:
        return None

    row = SearchCache.query.filter_by(query_hash=query_hash(query_dict)).first()
    if row is None:
        return None

    age = datetime.now(timezone.utc) - _as_utc(row.created_at)
    if age > timedelta(seconds=ttl_seconds):
        return None
    return row.crawl_id


def set_cache(query_dict: dict, crawl_id: str) -> None:
    h = query_hash(query_dict)
    row = SearchCache.query.filter_by(query_hash=h).first()
    if row is None:
        db.session.add(SearchCache(query_hash=h, crawl_id=crawl_id))
    else:
        row.crawl_id = crawl_id
        row.created_at = datetime.now(timezone.utc)
    db.session.commit()
