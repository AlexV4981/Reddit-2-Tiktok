"""Scrape weekly rankings and complete post bodies with Selenium, without Reddit API keys."""

from __future__ import annotations

import re
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.support.ui import WebDriverWait

from .browser import open_browser
from .config import Config
from .errors import AppError
from .models import Post as Post
from .reddit_html import parse_body, parse_listing


def subreddit_name(value: str) -> str:
    value = value.strip().removeprefix("/r/").removeprefix("r/").rstrip("/")
    if not re.fullmatch(r"[A-Za-z0-9_]{2,21}", value):
        raise AppError("Enter a subreddit name, such as AskReddit or r/AskReddit.")
    return value


class RedditClient:
    def __init__(
        self,
        config: Config,
        config_file: Path,
        *,
        browser_factory=open_browser,
        base_url: str | None = None,
    ):
        self.config, self.config_file = config, config_file
        self.browser_factory = browser_factory
        # An injection seam for offline browser fixtures, not a CLI flag.
        self.base_url = base_url or f"https://{config.reddit_frontend}.reddit.com"

    def _wait(self, driver, function):
        return WebDriverWait(driver, self.config.browser_timeout, poll_frequency=0.25).until(
            function
        )

    def _listing(self, driver, name):
        def loaded(_):
            listing = parse_listing(driver.page_source, self.base_url, name)
            return listing if listing.posts or listing.empty else False

        return self._wait(driver, loaded)

    def top_week(self, name: str) -> list[Post]:
        name = subreddit_name(name)
        try:
            with self.browser_factory(self.config, self.config_file) as driver:
                url = f"{self.base_url}/r/{name}/top/?t=week&limit=10"
                driver.get(url)
                posts: dict[str, Post] = {}
                visited = {url}
                for _ in range(5):
                    listing = self._listing(driver, name)
                    for post in listing.posts:
                        posts.setdefault(post.id, post)
                        if len(posts) == 10:
                            break
                    if len(posts) == 10 or listing.empty:
                        break
                    if listing.next_url and listing.next_url not in visited:
                        parts = urlsplit(listing.next_url)
                        params = dict(parse_qsl(parts.query))
                        params.update(t="week", limit="10")
                        url = urlunsplit(parts._replace(query=urlencode(params)))
                        if url in visited:
                            break
                        visited.add(url)
                        time.sleep(self.config.scrape_delay)
                        driver.get(url)
                    else:
                        previous = set(posts)
                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
                        try:
                            WebDriverWait(
                                driver, min(5, self.config.browser_timeout), poll_frequency=0.25
                            ).until(
                                lambda _, previous=previous: (
                                    set(
                                        p.id
                                        for p in parse_listing(
                                            driver.page_source, self.base_url, name
                                        ).posts
                                    )
                                    - previous
                                )
                            )
                        except TimeoutException:
                            break
                completed = []
                for post in posts.values():
                    time.sleep(self.config.scrape_delay)
                    driver.get(post.url)

                    def loaded_body(_, identity=post.id):
                        body = parse_body(driver.page_source, identity)
                        return (body,) if body is not None else False

                    body = self._wait(driver, loaded_body)[0]
                    completed.append(replace(post, body=body))
                return completed
        except TimeoutException as exc:
            raise AppError(
                "Reddit did not load the expected listing or full post body before the timeout. "
                "No partial scrape was saved. Retry later or check for a Reddit layout/access change."
            ) from exc
        except WebDriverException as exc:
            raise AppError(
                "The Selenium browser failed during scraping. Run 'doctor --browser' and retry."
            ) from exc
