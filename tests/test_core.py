import json
import math
import os
import random
from dataclasses import replace
from pathlib import Path

import pytest

from reddit2tiktok.captions import caption_text, write_ass
from reddit2tiktok.config import Config, load_config, resolve_path, save_config
from reddit2tiktok.errors import AppError
from reddit2tiktok.media import Background, Media
from reddit2tiktok.reddit import subreddit_name
from reddit2tiktok.store import Store
from reddit2tiktok.text import narration_text, plain_text, terminal_text
from reddit2tiktok.tts import EdgeNarrator, Word, validate_words


def test_config_roundtrip_is_relative_to_config_not_cwd(config, tmp_path, monkeypatch):
    path = tmp_path / "settings" / "config.json"
    save_config(path, config)
    monkeypatch.chdir(tmp_path.parent)
    assert load_config(path) == config
    assert resolve_path("data", path) == tmp_path / "settings" / "data"
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "changes",
    [
        {"verbose": "false"},
        {"width": 361},
        {"width": 720, "height": 1920},
        {"caption_y": float("nan")},
        {"rate": "fast"},
        {"rate": "+200%"},
        {"font": "fake,Injected"},
        {"data_dir": ""},
        {"fps": True},
        {"preset": "unknown"},
        {"browser_headless": "false"},
        {"reddit_frontend": []},
        {"reddit_frontend": "elsewhere"},
        {"browser_timeout": 0},
        {"browser_binary": None},
        {"chromedriver": "unsafe\npath"},
        {"scrape_delay": -1},
        {"scrape_delay": float("nan")},
    ],
)
def test_config_rejects_invalid_values(config, changes):
    with pytest.raises(AppError):
        replace(config, **changes).validate()


def test_config_invalid_json_and_unknown_keys(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("[broken", encoding="utf-8")
    with pytest.raises(AppError, match="Cannot read"):
        load_config(path)
    path.write_text('{"video_dir":"videos","typo":true}', encoding="utf-8")
    with pytest.raises(AppError, match="Unknown"):
        load_config(path)


def test_markdown_links_html_and_terminal_controls():
    value = "# Story\n\n**Hello** [world](https://example.com).<br>\nNext paragraph."
    assert plain_text(value) == "Story Hello world. Next paragraph."
    assert "https" not in plain_text("Go to https://example.com or [this](https://example.com)")
    assert "alert" not in plain_text("<script>alert('x')</script>Hello")
    assert narration_text("My day", "The story.") == "My day.\n\nThe story."
    assert terminal_text("\x1b[31mHello\x1b[0m\nworld\x00") == "Hello world"


@pytest.mark.parametrize(
    "value,expected", [("stories", "stories"), ("r/stories", "stories"), ("/r/stories/", "stories")]
)
def test_subreddit_names(value, expected):
    assert subreddit_name(value) == expected


@pytest.mark.parametrize(
    "value", ["../config", "a/b", "https://reddit.com/r/stories", "foo+bar", ""]
)
def test_subreddit_validation(value):
    with pytest.raises(AppError):
        subreddit_name(value)


def test_old_config_migrates_without_losing_preferences(config, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "video_dir": config.video_dir,
                "verbose": True,
                "voice": "en-GB-RyanNeural",
                "reddit_user_agent": "old-client",
            }
        )
    )
    migrated = load_config(path)
    assert migrated.verbose is True
    assert migrated.voice == "en-GB-RyanNeural"
    assert migrated.reddit_frontend == "old"
    assert migrated.browser_headless is True
    save_config(path, migrated)
    assert "reddit_user_agent" not in json.loads(path.read_text())


def test_store_deduplicates_and_preserves_history(tmp_path, post):
    store = Store(tmp_path / "posts.sqlite3")
    assert store.save([post, post]) == 1
    store.mark(post.id, "ready", output="video.mp4")
    assert store.save([replace(post, body="edited later")]) == 0
    row = store.get(post.id)
    assert row["status"] == "ready"
    assert row["body"] == post.body
    assert len(store.all()) == 1


def test_random_segments_always_fit_and_exclude_short_inputs():
    videos = [Background(Path("short.mp4"), 4), Background(Path("long.mp4"), 30)]
    starts = []
    rng = random.Random(123)
    for _ in range(20):
        video, start = Media.choose(videos, 10, rng)
        assert video.path.name == "long.mp4"
        assert 0 <= start <= 20
        starts.append(start)
    assert len(set(starts)) > 1
    video, start = Media.choose(videos, 30, rng)
    assert start == 0
    with pytest.raises(AppError, match="longer video"):
        Media.choose(videos, 31)


def test_word_captions_use_actual_timing_and_escape_markup(config, tmp_path):
    words = [Word("One", 0.1, 0.4), Word("two", 0.8, 1.2)]
    path = tmp_path / "captions.ass"
    write_ass(words, path, config, 1.5)
    text = path.read_text(encoding="utf-8")
    assert "0:00:00.10,0:00:00.40" in text
    assert "0:00:00.80,0:00:01.20" in text
    assert text.count("Dialogue:") == 2
    assert "\\pos(180,396)" in text
    assert "{" not in caption_text("{\\evil}text")
    assert "\\" not in caption_text("{\\evil}text")
    assert "\n" not in caption_text("new\nline")


@pytest.mark.parametrize(
    "words",
    [
        [],
        [Word("a", -1, 1)],
        [Word("a", 1, 0)],
        [Word("a", math.nan, 1)],
        [Word("a", 1, 2), Word("b", 0, 1)],
    ],
)
def test_bad_word_timing_is_rejected(words):
    with pytest.raises(AppError):
        validate_words(words)


def test_missing_word_timing_is_not_estimated(monkeypatch, tmp_path):
    class Stream:
        async def stream(self):
            yield {"type": "audio", "data": b"mp3"}

    monkeypatch.setattr("reddit2tiktok.tts.edge_tts.Communicate", lambda *a, **kw: Stream())
    with pytest.raises(AppError, match="no word timestamps"):
        EdgeNarrator("en-GB-RyanNeural", "+0%").synthesize("Hello", tmp_path / "narration.mp3")


def test_tts_explicitly_requests_word_boundaries(monkeypatch, tmp_path):
    options = {}

    class Stream:
        def __init__(self, text, voice, **kwargs):
            options.update(kwargs)

        async def stream(self):
            yield {"type": "audio", "data": b"mp3"}
            yield {
                "type": "WordBoundary",
                "text": "Hello",
                "offset": 2_000_000,
                "duration": 3_000_000,
            }

    monkeypatch.setattr("reddit2tiktok.tts.edge_tts.Communicate", Stream)
    words = EdgeNarrator("en-GB-RyanNeural", "+0%").synthesize("Hello", tmp_path / "audio.mp3")
    assert options["boundary"] == "WordBoundary"
    assert words == [Word("Hello", 0.2, 0.5)]


def test_config_example_matches_defaults():
    config = Config(**json.loads(Path("config.example.json").read_text()))
    config.validate()
