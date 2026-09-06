from dataclasses import replace

import aiohttp
import pytest

from reddit2tiktok.errors import AppError
from reddit2tiktok.media import Media
from reddit2tiktok.pipeline import Pipeline
from reddit2tiktok.store import Store
from reddit2tiktok.tts import EdgeNarrator
from tests.test_pipeline_cli import FakeMedia, FakeNarrator


def test_tts_retry_starts_fresh_audio_and_timing(monkeypatch, tmp_path):
    attempts = []

    class Stream:
        def __init__(self, *args, **kwargs):
            attempts.append(self)

        async def stream(self):
            if len(attempts) == 1:
                yield {"type": "audio", "data": b"partial"}
                raise aiohttp.ClientConnectionError("connection reset")
            yield {"type": "audio", "data": b"complete"}
            yield {
                "type": "WordBoundary",
                "text": "Hello",
                "offset": 1_000_000,
                "duration": 2_000_000,
            }

    async def no_wait(seconds):
        pass

    monkeypatch.setattr("reddit2tiktok.tts.edge_tts.Communicate", Stream)
    monkeypatch.setattr("reddit2tiktok.tts.asyncio.sleep", no_wait)
    audio = tmp_path / "narration.mp3"
    words = EdgeNarrator("en-GB-RyanNeural", "+0%").synthesize("Hello", audio)
    assert len(attempts) == 2
    assert audio.read_bytes() == b"complete"
    assert len(words) == 1
    assert words[0].start == 0.1


def test_media_executable_paths_resolve_beside_config(config, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path.parent)
    config = replace(config, ffmpeg="tools/ffmpeg", ffprobe="tools/ffprobe")
    media = Media(config, tmp_path / "config.json")
    assert media.ffmpeg == str(tmp_path / "tools" / "ffmpeg")
    assert media.ffprobe == str(tmp_path / "tools" / "ffprobe")


def test_interrupt_leaves_saved_post_retryable(config, tmp_path, post):
    class InterruptedNarrator(FakeNarrator):
        def synthesize(self, text, path):
            raise KeyboardInterrupt

    store = Store(tmp_path / "posts.sqlite3")
    store.save([post])
    pipeline = Pipeline(
        config, tmp_path / "config.json", store, InterruptedNarrator(), FakeMedia(), lambda _: None
    )
    with pytest.raises(KeyboardInterrupt):
        pipeline.render([post.id])
    assert store.get(post.id)["status"] == "failed"
    pipeline.narrator = FakeNarrator()
    assert pipeline.render([post.id]).ready == 1


def test_video_input_cannot_include_generated_output(config, tmp_path, post):
    store = Store(tmp_path / "posts.sqlite3")
    store.save([post])
    config = replace(config, video_dir=str(tmp_path))
    pipeline = Pipeline(
        config, tmp_path / "config.json", store, FakeNarrator(), FakeMedia(), lambda _: None
    )
    with pytest.raises(AppError, match="outside the background"):
        pipeline.render([post.id])
