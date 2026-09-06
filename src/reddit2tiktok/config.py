from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from urllib.parse import urlsplit

from .errors import AppError
from .voices import KOKORO_VOICES


@dataclass(frozen=True)
class Config:
    video_dir: str
    verbose: bool = False
    voice: str = "bm_daniel"
    tts_engine: str = "kokoro"
    rate: str = "+0%"
    data_dir: str = "data"
    output_dir: str = "ready4upload"
    reddit_frontend: str = "old"
    browser_binary: str = ""
    chromedriver: str = ""
    browser_remote_url: str = ""
    browser_headless: bool = True
    browser_timeout: int = 30
    scrape_delay: float = 1.0
    width: int = 1080
    height: int = 1920
    fps: int = 30
    font: str = "DejaVu Sans"
    font_size: int = 88
    caption_y: float = 0.62
    crf: int = 20
    preset: str = "medium"
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"

    def validate(self) -> None:
        for key in (
            "video_dir",
            "voice",
            "rate",
            "data_dir",
            "output_dir",
            "font",
            "ffmpeg",
            "ffprobe",
        ):
            value = getattr(self, key)
            if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
                raise AppError(
                    f"Config '{key}' must be a nonempty string without control characters."
                )
        if type(self.verbose) is not bool:
            raise AppError("Config 'verbose' must be true or false.")
        if not isinstance(self.tts_engine, str) or self.tts_engine not in {"kokoro", "edge"}:
            raise AppError("Config 'tts_engine' must be 'kokoro' or 'edge'.")
        if self.tts_engine == "kokoro" and self.voice not in KOKORO_VOICES:
            raise AppError(
                "Use a British Kokoro voice ID, such as bm_daniel, or select tts_engine=edge."
            )
        if type(self.browser_headless) is not bool:
            raise AppError("Config 'browser_headless' must be true or false.")
        if not isinstance(self.reddit_frontend, str) or self.reddit_frontend not in {"old", "www"}:
            raise AppError("Config 'reddit_frontend' must be 'old' or 'www'.")
        for key in ("browser_binary", "chromedriver"):
            value = getattr(self, key)
            if not isinstance(value, str) or any(ord(c) < 32 for c in value):
                raise AppError(f"Config '{key}' must be an executable path or an empty string.")
        if not isinstance(self.browser_remote_url, str):
            raise AppError("Config 'browser_remote_url' must be a URL or an empty string.")
        if self.browser_remote_url:
            try:
                remote = urlsplit(self.browser_remote_url)
                valid = (
                    remote.scheme in {"http", "https"}
                    and remote.hostname
                    and (remote.port is None or remote.port > 0)
                    and not (remote.username or remote.password or remote.query or remote.fragment)
                    and not any(c.isspace() or ord(c) < 32 for c in self.browser_remote_url)
                )
            except ValueError:
                valid = False
            if not valid:
                raise AppError("Remote Selenium needs an HTTP(S) URL without credentials or query.")
            if self.browser_binary or self.chromedriver:
                raise AppError(
                    "Remote Selenium cannot be combined with local browser/driver paths."
                )
        if type(self.scrape_delay) not in (int, float) or not 0 <= self.scrape_delay <= 60:
            raise AppError("Config 'scrape_delay' must be between 0 and 60 seconds.")
        for key, low, high in (
            ("width", 144, 2160),
            ("height", 256, 3840),
            ("fps", 1, 60),
            ("font_size", 12, 250),
            ("crf", 0, 51),
            ("browser_timeout", 1, 120),
        ):
            value = getattr(self, key)
            if type(value) is not int or not low <= value <= high:
                raise AppError(f"Config '{key}' must be an integer between {low} and {high}.")
        if self.width % 2 or self.height % 2 or self.width * 16 != self.height * 9:
            raise AppError("Video dimensions must be even and 9:16 (for example 1080x1920).")
        if type(self.caption_y) not in (int, float) or not 0.2 <= self.caption_y <= 0.8:
            raise AppError("Config 'caption_y' must be between 0.2 and 0.8.")
        if not re.fullmatch(r"[+-]\d{1,3}%", self.rate) or not -50 <= int(self.rate[:-1]) <= 100:
            raise AppError("Speech rate must be between -50% and +100%, including the sign.")
        if any(c in self.font for c in ",{}\\"):
            raise AppError("Caption font cannot contain commas, braces, or backslashes.")
        if self.preset not in {
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
            "slow",
            "slower",
            "veryslow",
        }:
            raise AppError("Invalid FFmpeg x264 preset.")


def resolve_path(value: str, config_file: Path) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else config_file.resolve().parent / path).resolve()


def load_config(path: Path) -> Config:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AppError(f"Cannot read configuration at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise AppError("Configuration must be a JSON object.")
    # v0.1 migration: Selenium uses the browser's own user agent.
    data.pop("reddit_user_agent", None)
    if "tts_engine" not in data:
        data.setdefault("voice", "en-GB-RyanNeural")
        data["tts_engine"] = (
            "kokoro"
            if isinstance(data["voice"], str) and data["voice"] in KOKORO_VOICES
            else "edge"
        )
    unknown = set(data) - {field.name for field in fields(Config)}
    if unknown:
        raise AppError(f"Unknown config keys: {', '.join(sorted(unknown))}")
    try:
        config = Config(**data)
    except TypeError as exc:
        raise AppError("Configuration requires 'video_dir'. Run the config command.") from exc
    config.validate()
    return config


def save_config(path: Path, config: Config) -> None:
    config.validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Restrictive mode on Linux, atomic replacement, and no secrets stored in this file.
    fd, temp = tempfile.mkstemp(prefix=".config-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(asdict(config), handle, indent=2)
            handle.write("\n")
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)
