import pytest
import requests
import responses

from app.utils import robots


@pytest.fixture(autouse=True)
def _reset_robots_cache():
    # robots.py caches a successfully-parsed RobotFileParser per domain for
    # the lifetime of the process - without resetting this between tests,
    # whichever test runs first for a given domain would decide the cached
    # result for every test after it.
    with robots._lock:
        robots._parsers.clear()
    yield
    with robots._lock:
        robots._parsers.clear()


@responses.activate
def test_is_allowed_true_when_robots_txt_allows_path():
    responses.add(
        responses.GET,
        "https://example.com/robots.txt",
        body="User-agent: *\nAllow: /\n",
        status=200,
    )
    assert robots.is_allowed("https://example.com/some/path", "TestBot/1.0") is True


@responses.activate
def test_is_allowed_false_when_robots_txt_disallows_path():
    responses.add(
        responses.GET,
        "https://example.com/robots.txt",
        body="User-agent: *\nDisallow: /private\n",
        status=200,
    )
    assert robots.is_allowed("https://example.com/private/data", "TestBot/1.0") is False
    assert robots.is_allowed("https://example.com/public/data", "TestBot/1.0") is True


@responses.activate
def test_is_allowed_false_when_robots_txt_fetch_raises_network_error():
    responses.add(
        responses.GET,
        "https://example.com/robots.txt",
        body=requests.exceptions.ConnectionError("boom"),
    )
    # Fail-closed: an unreachable robots.txt must block the scrape, not
    # silently allow it.
    assert robots.is_allowed("https://example.com/any/path", "TestBot/1.0") is False


@responses.activate
def test_is_allowed_false_when_robots_txt_returns_non_2xx():
    responses.add(responses.GET, "https://example.com/robots.txt", status=500)
    assert robots.is_allowed("https://example.com/any/path", "TestBot/1.0") is False


@responses.activate
def test_is_allowed_false_when_robots_txt_returns_404():
    responses.add(responses.GET, "https://example.com/robots.txt", status=404)
    assert robots.is_allowed("https://example.com/any/path", "TestBot/1.0") is False


@responses.activate
def test_successful_fetch_is_cached_and_not_refetched():
    responses.add(
        responses.GET,
        "https://example.com/robots.txt",
        body="User-agent: *\nAllow: /\n",
        status=200,
    )
    assert robots.is_allowed("https://example.com/a", "TestBot/1.0") is True
    assert robots.is_allowed("https://example.com/b", "TestBot/1.0") is True
    assert len(responses.calls) == 1


@responses.activate
def test_failed_fetch_is_not_cached_so_a_transient_failure_is_retried():
    responses.add(responses.GET, "https://example.com/robots.txt", status=500)
    responses.add(
        responses.GET,
        "https://example.com/robots.txt",
        body="User-agent: *\nAllow: /\n",
        status=200,
    )
    assert robots.is_allowed("https://example.com/a", "TestBot/1.0") is False
    assert robots.is_allowed("https://example.com/a", "TestBot/1.0") is True
    assert len(responses.calls) == 2


@responses.activate
def test_different_domains_are_fetched_and_cached_independently():
    responses.add(
        responses.GET,
        "https://allowed.example/robots.txt",
        body="User-agent: *\nAllow: /\n",
        status=200,
    )
    responses.add(
        responses.GET,
        "https://blocked.example/robots.txt",
        body="User-agent: *\nDisallow: /\n",
        status=200,
    )
    assert robots.is_allowed("https://allowed.example/x", "TestBot/1.0") is True
    assert robots.is_allowed("https://blocked.example/x", "TestBot/1.0") is False
