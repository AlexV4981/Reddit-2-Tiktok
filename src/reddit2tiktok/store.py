from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from .models import Post


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS posts (
                    id TEXT PRIMARY KEY, subreddit TEXT NOT NULL, title TEXT NOT NULL,
                    body TEXT NOT NULL, url TEXT NOT NULL, score INTEGER NOT NULL,
                    created_utc REAL NOT NULL,
                    scraped_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    status TEXT NOT NULL DEFAULT 'scraped', output_path TEXT, error TEXT,
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                )
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, posts: list[Post]) -> int:
        with self.connect() as db:
            before = db.total_changes
            db.executemany(
                """
                INSERT INTO posts (id,subreddit,title,body,url,score,created_utc)
                VALUES (:id,:subreddit,:title,:body,:url,:score,:created_utc)
                ON CONFLICT(id) DO NOTHING
            """,
                [asdict(post) for post in posts],
            )
            return db.total_changes - before

    def all(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM posts ORDER BY scraped_at,id")]

    def get(self, post_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
            return dict(row) if row else None

    def mark(
        self, post_id: str, status: str, output: str | None = None, error: str | None = None
    ) -> None:
        with self.connect() as db:
            db.execute(
                """UPDATE posts SET status=?,output_path=?,error=?,
                       updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (status, output, error, post_id),
            )
