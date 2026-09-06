import os
import shutil
from pathlib import Path

import pytest

from reddit2tiktok.config import Config
from reddit2tiktok.reddit import Post


@pytest.fixture
def config(tmp_path):
    videos = tmp_path / "background clips"
    videos.mkdir()
    return Config(
        video_dir=str(videos), width=360, height=640, fps=24, font_size=40, preset="ultrafast"
    )


@pytest.fixture
def post():
    return Post(
        "abc123",
        "stories",
        "An ordinary day",
        "Then something surprising happened.",
        "https://www.reddit.com/r/stories/comments/abc123/an_ordinary_day/",
        42,
        100.0,
    )


@pytest.fixture
def media_tools():
    ffmpeg = shutil.which(os.environ.get("R2T_FFMPEG", "ffmpeg"))
    ffprobe = shutil.which(os.environ.get("R2T_FFPROBE", "ffprobe"))
    if not ffmpeg or not ffprobe:
        if os.environ.get("R2T_REQUIRE_FFMPEG") == "1":
            pytest.fail("FFmpeg/ffprobe are required for this test run")
        pytest.skip("FFmpeg/ffprobe not installed")
    return str(Path(ffmpeg).resolve()), str(Path(ffprobe).resolve())


@pytest.fixture(autouse=True)
def no_reddit_credentials(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
