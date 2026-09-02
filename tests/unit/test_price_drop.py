from app.pricing.price_drop import detect_price_drops


def _point(source, price, scraped_at):
    return {"source": source, "selling_price": price, "scraped_at": scraped_at}


def test_falling_price_for_a_source_is_reported_as_a_drop():
    history = [
        _point("vijay_sales", 70000, "2026-09-01T10:00:00+00:00"),
        _point("vijay_sales", 65000, "2026-09-02T10:00:00+00:00"),
    ]
    drops = detect_price_drops(history)
    assert len(drops) == 1
    assert drops[0].source == "vijay_sales"
    assert drops[0].previous_price == 70000
    assert drops[0].current_price == 65000
    assert drops[0].drop_amount == 5000
    assert round(drops[0].drop_percent, 2) == round(5000 / 70000 * 100, 2)


def test_rising_or_flat_price_is_not_a_drop():
    rising = [
        _point("croma", 60000, "2026-09-01T10:00:00+00:00"),
        _point("croma", 62000, "2026-09-02T10:00:00+00:00"),
    ]
    flat = [
        _point("croma", 60000, "2026-09-01T10:00:00+00:00"),
        _point("croma", 60000, "2026-09-02T10:00:00+00:00"),
    ]
    assert detect_price_drops(rising) == []
    assert detect_price_drops(flat) == []


def test_single_scrape_for_a_source_is_never_a_drop():
    history = [_point("reliance_digital", 50000, "2026-09-01T10:00:00+00:00")]
    assert detect_price_drops(history) == []


def test_only_the_latest_two_scrapes_per_source_are_compared():
    # An earlier drop followed by a rebound above the previous low should
    # not still be reported once the price has gone back up.
    history = [
        _point("croma", 80000, "2026-08-01T10:00:00+00:00"),
        _point("croma", 70000, "2026-08-15T10:00:00+00:00"),
        _point("croma", 75000, "2026-09-01T10:00:00+00:00"),
    ]
    assert detect_price_drops(history) == []


def test_sources_are_compared_independently_not_against_each_other():
    history = [
        _point("croma", 90000, "2026-09-01T10:00:00+00:00"),
        _point("vijay_sales", 60000, "2026-09-01T10:05:00+00:00"),
        _point("vijay_sales", 58000, "2026-09-02T10:00:00+00:00"),
    ]
    drops = detect_price_drops(history)
    assert len(drops) == 1
    assert drops[0].source == "vijay_sales"


def test_listings_with_no_price_are_ignored():
    history = [
        _point("croma", None, "2026-09-01T10:00:00+00:00"),
        _point("croma", 50000, "2026-09-02T10:00:00+00:00"),
        _point("croma", 45000, "2026-09-03T10:00:00+00:00"),
    ]
    drops = detect_price_drops(history)
    assert len(drops) == 1
    assert drops[0].previous_price == 50000
    assert drops[0].current_price == 45000
