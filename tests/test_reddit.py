from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
from selenium.common.exceptions import WebDriverException

from reddit2tiktok.errors import AppError
from reddit2tiktok.reddit import RedditClient
from reddit2tiktok.reddit_html import parse_body, parse_listing, post_url
from tests.html_pages import legacy_card, modern_card

BASE = "https://old.reddit.com"


@pytest.mark.parametrize("card", [legacy_card, modern_card])
def test_listing_metadata_order_dedup_and_full_body_separation(card):
    page = card("abc1", "TRUNCATED") + card("abc0") + card("abc1")
    listing = parse_listing(page, BASE, "stories")
    assert [p.id for p in listing.posts] == ["abc1", "abc0"]
    assert listing.posts[0].title == "Story abc1"
    assert listing.posts[0].body == ""
    assert listing.posts[0].score == 123
    assert listing.posts[0].created_utc == 1788264000
    assert listing.posts[0].url == BASE + "/r/stories/comments/abc1/story/"


@pytest.mark.parametrize("card", [legacy_card, modern_card])
def test_body_uses_only_selected_post_not_comments_or_other_posts(card):
    page = card("other", "Not this") + card("abc0", "<p>Hello &amp; welcome.</p><p>The ending.</p>")
    page += '<div class="comment"><div class="md">A comment, not the story.</div></div>'
    assert parse_body(page, "abc0") == "Hello & welcome.\nThe ending."
    assert parse_body(card("abc0"), "abc0") is None
    assert parse_body(page, "missing") is None
    assert parse_body(card("abc0", "[removed]"), "abc0") == "[removed]"


def test_known_link_posts_are_empty_but_self_post_loading_is_not_empty():
    old_link = (
        legacy_card()
        .replace("thing link self", "thing link")
        .replace("self.stories", "example.org")
    )
    assert parse_body(old_link, "abc0") == ""
    assert parse_body(modern_card().replace('post-type="text"', 'post-type="image"'), "abc0") == ""
    assert parse_body(legacy_card(), "abc0") is None
    assert parse_body(modern_card(), "abc0") is None


def test_ads_pinned_crossposts_and_unsafe_ids_are_not_ranked():
    page = legacy_card("abc0", extra="promoted") + legacy_card("abc1", extra="stickied")
    page += modern_card("abc2", extra="is-promoted") + modern_card("abc3", extra="is-stickied")
    page += modern_card("../unsafe") + modern_card("abc4", modern_card("abc5"))
    assert [p.id for p in parse_listing(page, BASE, "stories").posts] == ["abc4"]


@pytest.mark.parametrize(
    "href",
    [
        "https://example.com/r/stories/comments/abc0/",
        "//evil.test/r/stories/comments/abc0/",
        "/r/elsewhere/comments/abc0/",
        "/r/stories/comments/other/",
        "javascript:alert(1)",
    ],
)
def test_navigation_rejects_external_or_wrong_posts(href):
    assert post_url(href, BASE, "stories", "abc0") is None


def test_next_links_must_stay_on_this_subreddit_and_frontend():
    for href in ("https://evil.test/", "/r/elsewhere/top/", "/r/stories/new/"):
        assert (
            parse_listing(f'<a rel="next" href="{href}">next</a>', BASE, "stories").next_url is None
        )
    page = '<span class="next-button"><a href="/r/stories/top/?after=t3_abc0">next</a></span>'
    assert parse_listing(page, BASE, "stories").next_url == BASE + "/r/stories/top/?after=t3_abc0"


def test_reddit_absolute_post_links_are_normalized_to_selected_frontend():
    page = modern_card().replace('permalink="/', 'permalink="https://www.reddit.com/')
    assert parse_listing(page, BASE, "stories").posts[0].url.startswith(BASE + "/r/")


@pytest.mark.parametrize(
    "message",
    [
        "You've been blocked by network security",
        "Verify you are human",
        "Too many requests",
        "This community is private",
    ],
)
def test_access_errors_stop_instead_of_reporting_an_empty_scrape(message):
    with pytest.raises(AppError):
        parse_listing(f"<h1>{message}</h1>", BASE, "stories")
    with pytest.raises(AppError):
        parse_body(f"<h1>{message}</h1>", "abc0")
    # A story about a blocked account must not trigger the access detector.
    assert parse_body(modern_card(body=message), "abc0") == message


def test_empty_listing_is_distinct_from_an_unknown_or_loading_page():
    assert parse_listing(
        '<p class="listing-info">there doesn\'t seem to be anything here</p>', BASE, "stories"
    ).empty
    assert not parse_listing("<p>Loading...</p>", BASE, "stories").empty


@contextmanager
def fake_browser(driver):
    try:
        yield driver
    finally:
        driver.quit()


def client_with_pages(config, tmp_path, pages):
    driver = MagicMock()
    driver.get.side_effect = lambda url: setattr(driver, "page_source", pages(url))
    config = replace(config, scrape_delay=0, browser_timeout=1)
    client = RedditClient(
        config, tmp_path / "config.json", browser_factory=lambda *a: fake_browser(driver)
    )
    return client, driver


def test_selenium_paginates_week_caps_ten_and_fetches_full_bodies(config, tmp_path):
    def pages(url):
        parts = urlsplit(url)
        if "/top/" in parts.path:
            query = parse_qs(parts.query)
            assert query["t"] == ["week"] and query["limit"] == ["10"]
            if "after" in query:
                return "".join(legacy_card(f"abc{i}", "truncated") for i in range(4, 13))
            return "".join(legacy_card(f"abc{i}", "truncated") for i in range(5)) + (
                '<a rel="next" href="/r/stories/top/?t=all&amp;after=t3_abc4">next</a>'
            )
        identity = parts.path.split("/")[4]
        return legacy_card(identity, f"The full story for {identity}.")

    client, driver = client_with_pages(config, tmp_path, pages)
    posts = client.top_week("r/stories")
    assert [p.id for p in posts] == [f"abc{i}" for i in range(10)]
    assert all(p.body == f"The full story for {p.id}." for p in posts)
    assert driver.get.call_count == 12
    driver.quit.assert_called_once()


def test_modern_infinite_scroll_loads_remaining_ranked_posts(config, tmp_path):
    def pages(url):
        if "/top/" in url:
            return "".join(modern_card(f"abc{i}") for i in range(5))
        return modern_card(urlsplit(url).path.split("/")[4], "Complete story")

    client, driver = client_with_pages(config, tmp_path, pages)
    driver.execute_script.side_effect = lambda _: setattr(
        driver, "page_source", "".join(modern_card(f"abc{i}") for i in range(10))
    )
    assert len(client.top_week("stories")) == 10
    driver.execute_script.assert_called_once()
    driver.quit.assert_called_once()


@pytest.mark.parametrize(
    "content,error",
    [
        ("Loading forever", "No partial scrape was saved"),
        ("You've been blocked by network security", "blocked"),
    ],
)
def test_browser_closed_on_timeout_or_block(config, tmp_path, content, error):
    client, driver = client_with_pages(config, tmp_path, lambda _: content)
    with pytest.raises(AppError, match=error):
        client.top_week("stories")
    driver.quit.assert_called_once()


def test_driver_failure_is_actionable_and_closed(config, tmp_path):
    client, driver = client_with_pages(config, tmp_path, lambda _: "")
    driver.get.side_effect = WebDriverException("browser gone")
    with pytest.raises(AppError, match="doctor --browser"):
        client.top_week("stories")
    driver.quit.assert_called_once()


def test_fewer_than_ten_available_posts_are_returned(config, tmp_path):
    client, driver = client_with_pages(config, tmp_path, lambda _: legacy_card(body="Full story"))
    assert len(client.top_week("stories")) == 1
    driver.quit.assert_called_once()
