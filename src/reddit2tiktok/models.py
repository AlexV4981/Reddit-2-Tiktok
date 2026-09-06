"""Shared domain objects, independent of browser, storage, and speech providers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Post:
    id: str
    subreddit: str
    title: str
    body: str
    url: str
    score: int = 0
    created_utc: float = 0
