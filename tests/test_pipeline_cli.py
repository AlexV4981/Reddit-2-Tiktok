import json
from dataclasses import replace
from pathlib import Path

import pytest

from reddit2tiktok.cli import main, print_posts, wizard
from reddit2tiktok.config import load_config, save_config
from reddit2tiktok.errors import AppError
from reddit2tiktok.media import Background
from reddit2tiktok.pipeline import Pipeline, render_lock
from reddit2tiktok.store import Store
from reddit2tiktok.tts import Word


class FakeNarrator:
    def __init__(self):
        self.calls = 0

    def synthesize(self, text, path):
        self.calls += 1
        path.write_bytes(b"audio fixture")
        return [Word("Test", 0.1, 1.8)]


class FakeMedia:
    def check_tools(self):
        pass

    def backgrounds(self, folder):
        return [Background(folder / "clip.mp4", 10)], []

    def probe(self, path):
        return {}

    def duration(self, info, stream):
        return 2.0

    def choose(self, videos, duration):
        return videos[0], 3.0

    def render(self, background, start, audio, subtitles, output, duration):
        output.write_bytes(b"verified video fixture")

    def silent_copy(self, narrated, output, duration):
        output.write_bytes(b"verified silent fixture")


def test_pipeline_publish_skip_force_and_manifest(config, tmp_path, post):
    store = Store(tmp_path / "data" / "posts.sqlite3")
    store.save([post])
    narrator = FakeNarrator()
    pipeline = Pipeline(
        config, tmp_path / "config.json", store, narrator, FakeMedia(), lambda _: None
    )
    assert pipeline.render([post.id]).ready == 1
    first = Path(store.get(post.id)["output_path"])
    assert first.parent.parent == tmp_path / "ready4upload"
    assert first.read_bytes() == b"verified video fixture"
    assert first.name == "with_voice.mp4"
    silent = Path(store.get(post.id)["silent_output_path"])
    assert silent == first.with_name("without_voice.mp4")
    assert silent.read_bytes() == b"verified silent fixture"
    manifest = json.loads(
        next((tmp_path / "data" / "artifacts").glob("*/manifest.json")).read_text()
    )
    assert manifest["start"] == 3.0
    assert manifest["voice"] == "en-GB-RyanNeural"
    assert manifest["url"] == post.url
    assert pipeline.render([post.id]).skipped == 1
    assert narrator.calls == 1
    assert pipeline.render([post.id], force=True).ready == 1
    assert Path(store.get(post.id)["output_path"]) != first
    assert first.is_file()


def test_failed_output_is_not_published_and_batch_continues(config, tmp_path, post):
    class FailOnce(FakeMedia):
        count = 0

        def render(self, background, start, audio, subtitles, output, duration):
            self.count += 1
            output.write_bytes(b"partial")
            if self.count == 1:
                raise AppError("encoder failure")

    store = Store(tmp_path / "data" / "posts.sqlite3")
    second = replace(post, id="other123")
    store.save([post, second])
    pipeline = Pipeline(
        config, tmp_path / "config.json", store, FakeNarrator(), FailOnce(), lambda _: None
    )
    result = pipeline.render([post.id, second.id])
    assert (result.ready, result.failed) == (1, 1)
    assert store.get(post.id)["status"] == "failed"
    assert len(list((tmp_path / "ready4upload").rglob("*.mp4"))) == 2
    assert not list((tmp_path / "ready4upload").glob(".render-*"))
    assert pipeline.render([post.id]).ready == 1


@pytest.mark.parametrize("body", ["", "[removed]", "[deleted]", "   "])
def test_empty_body_saved_but_skipped(config, tmp_path, post, body):
    store = Store(tmp_path / "posts.sqlite3")
    store.save([replace(post, body=body)])
    narrator = FakeNarrator()
    result = Pipeline(
        config, tmp_path / "config.json", store, narrator, FakeMedia(), lambda _: None
    ).render([post.id])
    assert result.skipped == 1
    assert narrator.calls == 0
    assert len(store.all()) == 1


def test_render_lock_releases_after_exception(tmp_path):
    with pytest.raises(RuntimeError), render_lock(tmp_path):
        with pytest.raises(AppError, match="Another render"):
            with render_lock(tmp_path):
                pass
        raise RuntimeError("interrupted")
    with render_lock(tmp_path):
        pass


def test_nonverbose_titles_only_and_verbose_adds_link(tmp_path, post, capsys):
    store = Store(tmp_path / "posts.sqlite3")
    store.save([post])
    print_posts(store.all(), False)
    assert capsys.readouterr().out == post.title + "\n"
    print_posts(store.all(), True)
    assert capsys.readouterr().out == post.title + "\n" + post.url + "\n"


def test_first_run_wizard(config, tmp_path, monkeypatch):
    replies = iter(["n", config.video_dir, ""])
    monkeypatch.setattr("builtins.input", lambda _: next(replies))
    path = tmp_path / "config.json"
    result = wizard(path)
    assert result.verbose is False
    assert result.voice == "bm_daniel"
    assert result.tts_engine == "kokoro"
    assert load_config(path) == result


def test_noninteractive_setup_commands_and_help(config, tmp_path, capsys, monkeypatch):
    path = tmp_path / "config.json"
    root = ["--config", str(path)]
    assert main([*root, "--verbose", "config", "--video-dir", config.video_dir]) == 0
    assert load_config(path).verbose is True
    assert main([*root, "--quiet", "config", "--rate=+10%"]) == 0
    assert load_config(path).verbose is False
    assert load_config(path).rate == "+10%"
    assert main([*root, "posts", "--json"]) == 0
    assert "[]" in capsys.readouterr().out
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(root) == 1
    assert "menu needs a terminal" in capsys.readouterr().err
    with pytest.raises(SystemExit) as code:
        main(["--help"])
    assert code.value.code == 0


def test_unattended_missing_config_fails_without_prompt(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(["--config", str(tmp_path / "missing.json"), "scrape", "stories"]) == 1
    assert "before unattended use" in capsys.readouterr().err


def test_cli_scrape_only_fetches_and_lists(config, tmp_path, post, monkeypatch, capsys):
    path = tmp_path / "config.json"
    save_config(path, config)
    monkeypatch.setattr("reddit2tiktok.cli.RedditClient.top_week", lambda self, name: [post])
    assert main(["--config", str(path), "scrape", "stories", "--scrape-only"]) == 0
    output = capsys.readouterr().out
    assert post.title in output
    assert post.url not in output
    assert Store(tmp_path / "data" / "posts.sqlite3").get(post.id)["body"] == post.body
