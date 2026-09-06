from __future__ import annotations

import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from .captions import write_ass
from .config import Config, resolve_path
from .errors import AppError
from .media import Media
from .store import Store, outputs_exist
from .text import narration_text, plain_text, terminal_text
from .tts import create_narrator, validate_words


@contextmanager
def render_lock(folder: Path):
    """OS-owned lock: released after crashes, with no stale PID files to remove."""
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "render.lock").open("a+b") as handle:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                if not handle.read(1):
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise AppError(
                "Another render is running for this data folder. Try again when it finishes."
            ) from exc
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


@dataclass
class BatchResult:
    ready: int = 0
    failed: int = 0
    skipped: int = 0


class Pipeline:
    def __init__(
        self,
        config: Config,
        config_file: Path,
        store: Store,
        narrator=None,
        media=None,
        report=print,
    ):
        self.config, self.store, self.report = config, store, report
        self.video_dir = resolve_path(config.video_dir, config_file)
        self.data_dir = resolve_path(config.data_dir, config_file)
        self.output_dir = resolve_path(config.output_dir, config_file)
        self.narrator = narrator or create_narrator(config, config_file)
        self.media = media or Media(config, config_file)

    def prepare(self):
        for path in (self.data_dir, self.output_dir):
            if path.is_relative_to(self.video_dir):
                raise AppError(
                    "Data and output folders must be outside the background videos folder."
                )
        self.media.check_tools()
        videos, warnings = self.media.backgrounds(self.video_dir)
        for warning in warnings:
            self.report(terminal_text(warning))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return videos

    def render(self, ids: list[str], force: bool = False) -> BatchResult:
        result = BatchResult()
        if not ids:
            return result
        with render_lock(self.data_dir):
            videos = self.prepare()
            for post_id in dict.fromkeys(ids):
                row = self.store.get(post_id)
                if row is None:
                    raise AppError(f"No scraped post with ID {post_id}.")
                title = terminal_text(row["title"])
                self.report(title)
                if self.config.verbose:
                    self.report(row["url"])
                if row["status"] == "ready" and outputs_exist(row) and not force:
                    self.report("  Already ready; skipped.")
                    result.skipped += 1
                    continue
                if not plain_text(row["body"]) or row["body"].strip() in {"[removed]", "[deleted]"}:
                    self.store.mark(post_id, "skipped", error="No usable text body.")
                    self.report("  Skipped: no usable text body.")
                    result.skipped += 1
                    continue
                self.store.mark(post_id, "rendering")
                try:
                    artifact_root = self.data_dir / "artifacts"
                    artifact_root.mkdir(parents=True, exist_ok=True)
                    run_id = f"{post_id}-{uuid.uuid4().hex}"
                    artifact_dir = artifact_root / run_id
                    artifact_dir.mkdir()
                    text = narration_text(row["title"], row["body"])
                    audio = (
                        artifact_dir / f"narration{getattr(self.narrator, 'audio_suffix', '.mp3')}"
                    )
                    self.report("  Generating narration and word timings...")
                    words = self.narrator.synthesize(text, audio)
                    duration = self.media.duration(self.media.probe(audio), "audio")
                    validate_words(words, duration)
                    video, start = self.media.choose(videos, duration)
                    subtitles = artifact_dir / "captions.ass"
                    write_ass(words, subtitles, self.config, duration)
                    final_dir = self.output_dir / run_id
                    final = final_dir / "with_voice.mp4"
                    silent_final = final_dir / "without_voice.mp4"
                    metadata = {
                        "post_id": post_id,
                        "title": row["title"],
                        "url": row["url"],
                        "narration": text,
                        "voice": self.config.voice,
                        "tts_engine": self.config.tts_engine,
                        "rate": self.config.rate,
                        "duration": duration,
                        "background": str(video.path),
                        "start": start,
                        "output": str(final),
                        "silent_output": str(silent_final),
                        "words": [asdict(word) for word in words],
                    }
                    (artifact_dir / "manifest.json").write_text(
                        json.dumps(metadata, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    self.report(f"  Rendering {duration:.1f}s of captioned video...")
                    # Publish both verified files together by renaming their directory on
                    # the output filesystem; a crash must not expose half a completed pair.
                    with tempfile.TemporaryDirectory(
                        prefix=".render-", dir=self.output_dir
                    ) as temp:
                        pair = Path(temp) / "pair"
                        pair.mkdir()
                        partial = pair / "with_voice.mp4"
                        self.media.render(video, start, audio, subtitles, partial, duration)
                        self.media.silent_copy(partial, pair / "without_voice.mp4", duration)
                        os.replace(pair, final_dir)
                    self.store.mark(
                        post_id, "ready", output=str(final), silent_output=str(silent_final)
                    )
                    result.ready += 1
                    self.report(f"  Ready: {final}")
                    self.report(f"  Silent copy: {silent_final}")
                except (AppError, OSError) as exc:
                    message = terminal_text(str(exc))
                    self.store.mark(post_id, "failed", error=message)
                    result.failed += 1
                    self.report(f"  Failed: {message}")
                except (KeyboardInterrupt, SystemExit):
                    self.store.mark(post_id, "failed", error="Interrupted; retry this post.")
                    raise
        return result
