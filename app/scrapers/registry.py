"""Adapter registry - adding a retailer is adding one file + one line here,
no changes to search_service.py or any other core code required.
"""

from app.scrapers.base import BaseAdapter
from app.scrapers.croma import CromaAdapter
from app.scrapers.reliance_digital import RelianceDigitalAdapter
from app.scrapers.vijay_sales import VijaySalesAdapter

SOURCE_ADAPTERS: dict[str, type[BaseAdapter]] = {
    CromaAdapter.source_name: CromaAdapter,
    VijaySalesAdapter.source_name: VijaySalesAdapter,
    RelianceDigitalAdapter.source_name: RelianceDigitalAdapter,
}


def available_sources() -> list[str]:
    return list(SOURCE_ADAPTERS.keys())
