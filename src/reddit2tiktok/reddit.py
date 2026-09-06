from __future__ import annotations

import os
import re
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .errors import AppError


@dataclass(frozen=True)
class Post:
    id: str
    subreddit: str
    title: str
    body: str
    url: str
    score: int = 0
    created_utc: float = 0


def subreddit_name(value: str) -> str:
    value = value.strip().removeprefix("/r/").removeprefix("r/").rstrip("/")
    if not re.fullmatch(r"[A-Za-z0-9_]{2,21}", value):
        raise AppError("Enter a subreddit name, such as AskReddit or r/AskReddit.")
    return value


class RedditClient:
    def __init__(self, user_agent: str, session=None) -> None:
        self.session = session or requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": user_agent})

    def top_week(self, name: str) -> list[Post]:
        name = subreddit_name(name)
        client_id = os.environ.get("REDDIT_CLIENT_ID", "")
        secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
        if bool(client_id) != bool(secret):
            raise AppError("Set both REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET, or neither.")
        try:
            headers = {}
            if client_id:
                response = self.session.post(
                    "https://www.reddit.com/api/v1/access_token",
                    auth=(client_id, secret),
                    data={"grant_type": "client_credentials"},
                    timeout=(10, 30),
                )
                response.raise_for_status()
                token = response.json().get("access_token")
                if not token:
                    raise AppError(
                        "Reddit did not return an OAuth token. Check your API credentials."
                    )
                headers["Authorization"] = f"bearer {token}"
                url = f"https://oauth.reddit.com/r/{name}/top"
            else:
                url = f"https://www.reddit.com/r/{name}/top.json"
            response = self.session.get(
                url,
                params={"t": "week", "limit": 10, "raw_json": 1},
                headers=headers,
                timeout=(10, 30),
            )
            response.raise_for_status()
            payload = response.json()
            children = payload["data"]["children"]
            if not isinstance(children, list):
                raise ValueError("missing post listing")
            posts: list[Post] = []
            seen = set()
            for child in children[:10]:
                if child.get("kind") != "t3":
                    continue
                item = child["data"]
                post_id = str(item["id"])
                if not re.fullmatch(r"[a-z0-9]+", post_id) or post_id in seen:
                    continue
                title = item.get("title")
                body = item.get("selftext") or ""
                if not isinstance(title, str) or not isinstance(body, str):
                    raise ValueError("invalid post text")
                permalink = item["permalink"]
                if not isinstance(permalink, str) or not permalink.startswith("/r/"):
                    raise ValueError("invalid post permalink")
                seen.add(post_id)
                posts.append(
                    Post(
                        post_id,
                        name,
                        title,
                        body,
                        "https://www.reddit.com" + permalink,
                        int(item.get("score", 0)),
                        float(item.get("created_utc", 0)),
                    )
                )
            return posts
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            raise AppError(
                f"Reddit returned HTTP {status}. Check the subreddit and API access. "
                "Server IPs may need approved Reddit OAuth credentials; set REDDIT_CLIENT_ID "
                "and REDDIT_CLIENT_SECRET. Private, banned, or quarantined communities may be unavailable."
            ) from exc
        except requests.RequestException as exc:
            raise AppError(
                "Cannot reach Reddit. Check network connectivity and try again."
            ) from exc
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise AppError("Reddit returned an unexpected response; no posts were saved.") from exc
        finally:
            self.session.close()
