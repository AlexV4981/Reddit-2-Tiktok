from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from pathlib import Path

import aiohttp
import edge_tts

from .errors import AppError


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


def validate_words(words: list[Word], duration: float | None = None) -> None:
    if not words:
        raise AppError("TTS returned no word timestamps; captions cannot be synchronized.")
    previous = -1.0
    for word in words:
        if (
            not word.text.strip()
            or not math.isfinite(word.start)
            or not math.isfinite(word.end)
            or word.start < 0
            or word.end <= word.start
            or word.start <= previous
        ):
            raise AppError("TTS returned invalid or unordered word timestamps.")
        if duration is not None and (word.start >= duration or word.end > duration + 0.15):
            raise AppError("TTS word timestamps extend beyond the narration audio.")
        previous = word.start


class EdgeNarrator:
    def __init__(self, voice: str, rate: str):
        self.voice, self.rate = voice, rate

    def synthesize(self, text: str, destination: Path) -> list[Word]:
        try:
            return asyncio.run(self._synthesize(text, destination))
        except ValueError as exc:
            raise AppError(
                "Invalid speech settings. Check the voice ID and rate in config."
            ) from exc

    async def _synthesize(self, text: str, destination: Path) -> list[Word]:
        if not text.strip():
            raise AppError("The post contains no readable narration text.")
        for attempt in range(3):
            words: list[Word] = []
            try:
                communicate = edge_tts.Communicate(
                    text,
                    self.voice,
                    rate=self.rate,
                    boundary="WordBoundary",
                    connect_timeout=10,
                    receive_timeout=60,
                )
                # Starting over on retry prevents duplicate audio and stale word offsets.
                with destination.open("wb") as audio:
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            audio.write(chunk["data"])
                        elif chunk["type"] == "WordBoundary":
                            start = chunk["offset"] / 10_000_000
                            words.append(
                                Word(chunk["text"], start, start + chunk["duration"] / 10_000_000)
                            )
                if not destination.stat().st_size:
                    raise AppError("TTS returned empty audio.")
                validate_words(words)
                return words
            except (aiohttp.ClientError, TimeoutError, edge_tts.exceptions.EdgeTTSException) as exc:
                destination.unlink(missing_ok=True)
                if attempt == 2:
                    raise AppError(
                        f"Speech generation failed after 3 attempts ({type(exc).__name__}). "
                        "Check connectivity and the configured voice; use 'voices' to list voices."
                    ) from exc
                await asyncio.sleep(2**attempt)
        raise AssertionError("unreachable")


async def available_voices() -> list[dict]:
    try:
        return await edge_tts.list_voices()
    except (aiohttp.ClientError, TimeoutError, edge_tts.exceptions.EdgeTTSException) as exc:
        raise AppError(
            "Unable to fetch Microsoft's voice list. Check network connectivity."
        ) from exc
