"""Real headless Chrome exercises rendered DOM and the CLI without contacting Reddit."""

from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import pytest

from reddit2tiktok.cli import main
from reddit2tiktok.config import save_config
from reddit2tiktok.reddit import RedditClient
from reddit2tiktok.store import Store
from tests.html_pages import delayed, legacy_card, modern_card

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("card", [legacy_card, modern_card])
def test_real_browser_waits_for_dom_paginates_and_saves_full_top_ten(
    browser_config,
    tmp_path,
    html_server,
    monkeypatch,
    card,
):
    base, routes, visits = html_server
    routes["/r/stories/top/?t=week&limit=10"] = delayed(
        "".join(card(f"abc{i}", "TRUNCATED PREVIEW") for i in range(5))
        + '<a rel="next" href="/r/stories/top/?t=all&amp;after=t3_abc4">next</a>'
    )
    routes["/r/stories/top/?t=week&after=t3_abc4&limit=10"] = delayed(
        "".join(card(f"abc{i}", "TRUNCATED PREVIEW") for i in range(4, 12))
    )
    for index in range(10):
        routes[f"/r/stories/comments/abc{index}/story/"] = delayed(
            card(f"abc{index}", f"<p>Full story {index}.</p><p>This is the ending.</p>"),
            initial=card(f"abc{index}"),
        )
    path = tmp_path / "config.json"
    save_config(path, browser_config)
    monkeypatch.setattr(
        "reddit2tiktok.cli.RedditClient",
        lambda config, file: RedditClient(config, file, base_url=base),
    )
    assert main(["--config", str(path), "scrape", "stories", "--scrape-only"]) == 0
    rows = Store(tmp_path / "data" / "posts.sqlite3").all()
    assert len(rows) == 10
    assert {row["id"] for row in rows} == {f"abc{i}" for i in range(10)}
    for row in rows:
        assert row["body"] == f"Full story {row['id'][3:]}.\nThis is the ending."
        assert row["status"] == "scraped"
    for url in visits:
        if "/top/" in url:
            assert parse_qs(urlsplit(url).query)["t"] == ["week"]
    assert len([url for url in visits if "/comments/" in url]) == 10
    assert not list((tmp_path / "data" / "browser-profiles").iterdir())


def test_real_browser_partial_scrape_not_saved_after_detail_block(
    browser_config,
    tmp_path,
    html_server,
    monkeypatch,
    capsys,
):
    base, routes, _ = html_server
    routes["/r/stories/top/?t=week&limit=10"] = "".join(modern_card(f"abc{i}") for i in range(10))
    routes["/r/stories/comments/abc0/story/"] = modern_card("abc0", "Complete story")
    routes["/r/stories/comments/abc1/story/"] = "<h1>You've been blocked by network security</h1>"
    path = tmp_path / "config.json"
    save_config(path, replace(browser_config, browser_timeout=2))
    monkeypatch.setattr(
        "reddit2tiktok.cli.RedditClient",
        lambda config, file: RedditClient(config, file, base_url=base),
    )
    assert main(["--config", str(path), "scrape", "stories", "--scrape-only"]) == 1
    assert "blocked" in capsys.readouterr().err
    assert Store(tmp_path / "data" / "posts.sqlite3").all() == []
    assert not list((tmp_path / "data" / "browser-profiles").iterdir())
