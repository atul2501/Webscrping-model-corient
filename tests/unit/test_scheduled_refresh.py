from scripts.scheduled_refresh import run_forever


def test_run_forever_runs_one_cycle_per_iteration_and_stops_at_max_iterations(app, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "scripts.scheduled_refresh.run_full_catalog_crawl",
        lambda app, requested, log: calls.append(list(requested)) or {"total_persisted": 0},
    )
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda seconds: sleeps.append(seconds))

    run_forever(app, ["vijay_sales"], interval_seconds=42, max_iterations=3)

    assert calls == [["vijay_sales"]] * 3
    # Sleeps between iterations only, not after the last one.
    assert sleeps == [42, 42]


def test_run_forever_survives_a_failed_cycle_and_keeps_going(app, monkeypatch):
    calls = {"n": 0}

    def flaky_crawl(app, requested, log):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated crawl failure")
        return {"total_persisted": 5}

    monkeypatch.setattr("scripts.scheduled_refresh.run_full_catalog_crawl", flaky_crawl)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    # Must not raise, despite the first cycle failing.
    run_forever(app, ["vijay_sales"], interval_seconds=1, max_iterations=2)

    assert calls["n"] == 2
