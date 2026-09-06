import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from reddit2tiktok.cli import main, pending_ids
from reddit2tiktok.config import load_config
from reddit2tiktok.errors import AppError
from reddit2tiktok.pipeline import Pipeline
from reddit2tiktok.store import Store
from tests.test_pipeline_cli import FakeMedia, FakeNarrator


def test_silent_export_failure_publishes_neither_file(config, tmp_path, post):
    class FailSilent(FakeMedia):
        def silent_copy(self, narrated, output, duration):
            output.write_bytes(b"partial silent file")
            raise AppError("silent remux failure")

    store = Store(tmp_path / "data" / "posts.sqlite3")
    store.save([post])
    pipeline = Pipeline(
        config, tmp_path / "config.json", store, FakeNarrator(), FailSilent(), lambda _: None
    )
    assert pipeline.render([post.id]).failed == 1
    assert store.get(post.id)["status"] == "failed"
    assert store.get(post.id)["output_path"] is None
    assert store.get(post.id)["silent_output_path"] is None
    assert list((tmp_path / "ready4upload").iterdir()) == []
    pipeline.media = FakeMedia()
    assert pipeline.render([post.id]).ready == 1
    assert len(list((tmp_path / "ready4upload").rglob("*.mp4"))) == 2


def test_missing_silent_file_is_pending_and_force_preserves_old_pairs(config, tmp_path, post):
    store = Store(tmp_path / "posts.sqlite3")
    store.save([post])
    pipeline = Pipeline(
        config, tmp_path / "config.json", store, FakeNarrator(), FakeMedia(), lambda _: None
    )
    assert pipeline.render([post.id]).ready == 1
    row = store.get(post.id)
    original_voice, original_silent = Path(row["output_path"]), Path(row["silent_output_path"])
    assert pending_ids(store) == []
    assert pipeline.render([post.id], force=True).ready == 1
    assert original_voice.exists() and original_silent.exists()
    current = store.get(post.id)
    Path(current["silent_output_path"]).unlink()
    assert pending_ids(store) == [post.id]
    assert pipeline.render([post.id]).ready == 1
    assert Path(current["output_path"]).exists()


def test_old_database_migrates_without_losing_saved_posts_or_exports(tmp_path):
    path = tmp_path / "posts.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE posts (
            id TEXT PRIMARY KEY, subreddit TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
            url TEXT NOT NULL, score INTEGER NOT NULL, created_utc REAL NOT NULL,
            scraped_at TEXT, status TEXT, output_path TEXT, error TEXT, updated_at TEXT)""")
        db.execute("""INSERT INTO posts VALUES (
            'abc0','stories','Saved title','Saved body','https://www.reddit.com/example',1,2,
            '2026-09-01','ready','old.mp4',NULL,'2026-09-01')""")
    store = Store(path)
    row = store.get("abc0")
    assert row["body"] == "Saved body"
    assert row["output_path"] == "old.mp4"
    assert row["silent_output_path"] is None
    assert Store(path).get("abc0") == row


def test_failed_force_retains_paths_to_previous_exports(config, tmp_path, post):
    store = Store(tmp_path / "posts.sqlite3")
    store.save([post])
    store.mark(post.id, "ready", output="old-voice.mp4", silent_output="old-silent.mp4")
    store.mark(post.id, "rendering")
    store.mark(post.id, "failed", error="Failed new version")
    assert store.get(post.id)["output_path"] == "old-voice.mp4"
    assert store.get(post.id)["silent_output_path"] == "old-silent.mp4"


def test_cli_switches_engines_and_lists_local_voices_without_network(config, tmp_path, capsys):
    path = tmp_path / "config.json"
    root = ["--config", str(path)]
    assert main([*root, "config", "--video-dir", config.video_dir]) == 0
    assert load_config(path).voice == "bm_daniel"
    assert main([*root, "config", "--tts-engine", "edge"]) == 0
    assert load_config(path).voice == "en-GB-RyanNeural"
    assert main([*root, "config", "--voice", "bm_george"]) == 0
    assert load_config(path).tts_engine == "kokoro"
    assert main(["voices", "--engine", "kokoro"]) == 0
    assert "bm_daniel" in capsys.readouterr().out


@pytest.mark.parametrize(
    "changes",
    [
        {"tts_engine": []},
        {"tts_engine": "unknown"},
        {"tts_engine": "kokoro", "voice": "../unsafe.pt"},
    ],
)
def test_invalid_engine_and_local_voice_paths_are_rejected(config, changes):
    with pytest.raises(AppError):
        replace(config, **changes).validate()
