from __future__ import annotations

import json
import math
import random
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Config, resolve_path
from .errors import AppError

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}


def run(command: list[str], *, cwd: Path | None = None, timeout: float = 60) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=True,
        )
        return result.stdout
    except FileNotFoundError as exc:
        raise AppError(f"Cannot find {command[0]}. Install FFmpeg and ffprobe.") from exc
    except subprocess.TimeoutExpired as exc:
        raise AppError(f"{Path(command[0]).name} timed out after {int(timeout)} seconds.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "unknown error").strip()[-1600:]
        raise AppError(f"{Path(command[0]).name} failed: {detail}") from exc


@dataclass(frozen=True)
class Background:
    path: Path
    duration: float


class Media:
    def __init__(self, config: Config, config_file: Path | None = None):
        self.config = config
        anchor = config_file or Path.cwd() / "config.json"

        def binary_path(value: str) -> str:
            if "/" in value or "\\" in value or value.startswith("~"):
                return str(resolve_path(value, anchor))
            found = shutil.which(value)
            return str(Path(found).resolve()) if found else value

        self.ffmpeg = binary_path(config.ffmpeg)
        self.ffprobe = binary_path(config.ffprobe)

    def check_tools(self) -> None:
        for binary in (self.ffmpeg, self.ffprobe):
            if not shutil.which(binary):
                raise AppError(f"Missing {binary}. On Debian/Ubuntu: sudo apt install ffmpeg")
        filters = run([self.ffmpeg, "-hide_banner", "-filters"])
        if not re.search(r"\bass\s+V->V", filters):
            raise AppError("FFmpeg needs the 'ass' filter (libass) to burn in captions.")
        encoders = run([self.ffmpeg, "-hide_banner", "-encoders"])
        if not re.search(r"\blibx264\s", encoders) or not re.search(r"\baac\s", encoders):
            raise AppError("FFmpeg needs libx264 and AAC encoders for upload-ready MP4 files.")

    def probe(self, path: Path) -> dict:
        output = run(
            [
                self.ffprobe,
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path.resolve()),
            ]
        )
        try:
            info = json.loads(output)
            if not isinstance(info.get("streams"), list):
                raise ValueError("missing streams")
            return info
        except (ValueError, AttributeError) as exc:
            raise AppError(f"Cannot read media metadata for {path.name}.") from exc

    @staticmethod
    def duration(info: dict, stream_type: str) -> float:
        stream = next((s for s in info["streams"] if s.get("codec_type") == stream_type), None)
        if stream is None:
            raise AppError(f"Media file has no {stream_type} stream.")
        try:
            value = stream.get("duration")
            if value in (None, "N/A"):
                value = info.get("format", {}).get("duration")
            duration = float(value)
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError("nonpositive duration")
            return duration
        except (ValueError, TypeError) as exc:
            raise AppError(f"Media file has no valid {stream_type} duration.") from exc

    def backgrounds(self, folder: Path) -> tuple[list[Background], list[str]]:
        if not folder.is_dir():
            raise AppError(f"Background videos folder does not exist: {folder}")
        videos, warnings = [], []
        for path in sorted(folder.rglob("*")):
            if path.suffix.lower() not in VIDEO_EXTENSIONS or not path.is_file():
                continue
            if not path.resolve().is_relative_to(folder.resolve()):
                continue
            try:
                info = self.probe(path)
                videos.append(Background(path.resolve(), self.duration(info, "video")))
            except AppError:
                warnings.append(f"Ignoring unreadable background: {path.name}")
        if not videos:
            raise AppError(
                f"No readable background videos in {folder}. Add an MP4, MOV, MKV, or WebM."
            )
        return videos, warnings

    @staticmethod
    def choose(videos: list[Background], duration: float, rng=None) -> tuple[Background, float]:
        eligible = [video for video in videos if video.duration >= duration]
        if not eligible:
            longest = max((v.duration for v in videos), default=0)
            raise AppError(
                f"Narration is {duration:.1f}s, but the longest background is {longest:.1f}s. "
                "Add a longer video to the configured folder and retry."
            )
        rng = rng or random.SystemRandom()
        video = rng.choice(eligible)
        return video, rng.uniform(0, video.duration - duration)

    def render(
        self,
        background: Background,
        start: float,
        audio: Path,
        subtitles: Path,
        output: Path,
        duration: float,
    ) -> None:
        cfg = self.config
        # Working beside a fixed subtitle filename avoids escaping arbitrary paths in a filter.
        if subtitles.name != "captions.ass":
            raise AppError("Internal subtitle filename must be captions.ass.")
        filters = (
            f"scale={cfg.width}:{cfg.height}:force_original_aspect_ratio=increase,"
            f"crop={cfg.width}:{cfg.height},setsar=1,fps={cfg.fps},ass=captions.ass"
        )
        run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-ss",
                f"{start:.6f}",
                "-i",
                str(background.path),
                "-i",
                str(audio.resolve()),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-vf",
                filters,
                "-af",
                "apad",
                "-t",
                f"{duration:.6f}",
                "-c:v",
                "libx264",
                "-preset",
                cfg.preset,
                "-crf",
                str(cfg.crf),
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                "-map_metadata",
                "-1",
                str(output.resolve()),
            ],
            cwd=subtitles.parent,
            timeout=max(600, duration * 30),
        )
        info = self.probe(output)
        video = next((s for s in info["streams"] if s.get("codec_type") == "video"), {})
        if (video.get("width"), video.get("height"), video.get("codec_name")) != (
            cfg.width,
            cfg.height,
            "h264",
        ):
            raise AppError("Rendered video failed the resolution/codec check.")
        for stream in ("video", "audio"):
            if abs(self.duration(info, stream) - duration) > max(0.15, 2 / cfg.fps):
                raise AppError(
                    f"Rendered {stream} duration does not match narration; export rejected."
                )
