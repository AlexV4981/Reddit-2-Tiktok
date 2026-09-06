"""Parse rendered Reddit HTML; isolate selector changes from browser orchestration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .errors import AppError
from .models import Post

POST_SELECTOR = 'shreddit-post[post-id], div.thing[data-fullname^="t3_"]'


@dataclass(frozen=True)
class Listing:
    posts: tuple[Post, ...]
    next_url: str | None = None
    empty: bool = False


def document(source: str) -> BeautifulSoup:
    return BeautifulSoup(source, "html.parser")


def check_access(soup: BeautifulSoup) -> None:
    # Story text must not accidentally be mistaken for a network block or CAPTCHA.
    if soup.select_one(POST_SELECTOR):
        return
    text = soup.get_text(" ", strip=True).lower()
    if any(
        phrase in text
        for phrase in (
            "blocked by network security",
            "whoa there, pardner",
            "you've been blocked",
            "verify you are human",
            "prove you're not a robot",
            "too many requests",
            "our cdn was unable to reach",
            "request has been blocked",
        )
    ):
        raise AppError(
            "Reddit blocked this browser or requested verification. No posts were saved. "
            "Try again later from an allowed network; Selenium does not bypass Reddit access checks."
        )
    if any(
        phrase in text
        for phrase in (
            "this community is private",
            "this community has been banned",
            "over 18",
            "you must be 18",
            "this community has been quarantined",
        )
    ):
        raise AppError("This subreddit requires access or age verification; scraping was stopped.")


def post_url(href: str, base: str, subreddit: str, post_id: str) -> str | None:
    parsed = urlsplit(urljoin(base, href))
    origin = urlsplit(base)
    match = re.match(r"^/r/([^/]+)/comments/([a-z0-9]+)(?:/|$)", parsed.path)
    if (
        parsed.scheme != origin.scheme
        or parsed.netloc != origin.netloc
        or not match
        or match[1].lower() != subreddit.lower()
        or match[2] != post_id
    ):
        return None
    return f"{origin.scheme}://{origin.netloc}{parsed.path}"


def _number(value: str) -> int:
    try:
        return int(value.replace(",", ""))
    except (TypeError, ValueError, AttributeError):
        return 0


def _created(card) -> float:
    value = card.get("created-timestamp")
    time = card.select_one("time[datetime]")
    value = value or (time.get("datetime") if time else None)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() if value else 0
    except (ValueError, TypeError):
        return 0


def parse_listing(source: str, base: str, subreddit: str) -> Listing:
    soup = document(source)
    check_access(soup)
    posts, seen = [], set()
    for card in soup.select(POST_SELECTOR):
        if card.find_parent("shreddit-post") or card.find_parent("div", class_="thing"):
            continue
        classes = set(card.get("class", []))
        if (
            "promoted" in classes
            or "stickied" in classes
            or card.has_attr("is-stickied")
            or card.has_attr("is-promoted")
            or card.get("promoted") == "true"
        ):
            continue
        identity = card.get("post-id", card.get("data-fullname", ""))
        if not re.fullmatch(r"t3_[a-z0-9]+", identity):
            continue
        post_id = identity[3:]
        if post_id in seen:
            continue
        anchor = card.select_one(
            'a[slot="full-post-link"], a.comments, a[data-click-id="comments"]'
        )
        href = card.get("permalink") or (anchor.get("href") if anchor else "")
        if urlsplit(href).hostname in {"www.reddit.com", "old.reddit.com", "reddit.com"}:
            href = urlsplit(href).path
        url = post_url(href, base, subreddit, post_id)
        title_node = card.select_one('a.title, [slot="title"], h1, h2, a[slot="full-post-link"]')
        title = card.get("post-title") or (
            title_node.get_text(" ", strip=True) if title_node else ""
        )
        if not url or not title:
            continue
        seen.add(post_id)
        # Listing bodies may be truncated; always load the selected post's detail page.
        posts.append(
            Post(
                post_id,
                subreddit,
                title,
                "",
                url,
                _number(card.get("score", card.get("data-score", "0"))),
                _created(card),
            )
        )
    next_url = None
    next_link = soup.select_one(".next-button a, a[rel='next']")
    if next_link:
        target = urlsplit(urljoin(base, next_link.get("href", "")))
        origin = urlsplit(base)
        if (
            target.netloc == origin.netloc
            and target.scheme == origin.scheme
            and target.path.rstrip("/").lower() == f"/r/{subreddit}/top".lower()
        ):
            next_url = target.geturl()
    empty = (
        bool(soup.select_one(".listing-info"))
        and not posts
        and any(
            phrase in soup.get_text(" ", strip=True).lower()
            for phrase in ("there doesn't seem to be anything here", "no posts", "no results")
        )
    )
    return Listing(tuple(posts), next_url, empty)


def parse_body(source: str, post_id: str) -> str | None:
    """None means not loaded/unknown layout; empty text means a known non-story post."""
    soup = document(source)
    check_access(soup)
    card = soup.select_one(f'shreddit-post[post-id="t3_{post_id}"]')
    if card:
        body = card.select_one('[slot="text-body"]')
        if body is not None:
            return body.get_text("\n", strip=True)
        if card.get("post-type") in {"image", "video", "link", "gallery"}:
            return ""
        if card.select_one('[slot="post-removed-banner"]'):
            return "[removed]"
        return None
    card = soup.select_one(f'div.thing[data-fullname="t3_{post_id}"]')
    if card:
        body = card.select_one(".expando .usertext-body .md")
        if body is not None:
            return body.get_text("\n", strip=True)
        classes = set(card.get("class", []))
        is_self = "self" in classes or card.get("data-domain", "").startswith("self.")
        if not is_self and (card.get("data-type") == "link" or "link" in classes):
            return ""
    return None
