"""Local British Kokoro speech with model-derived word timestamps."""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path

from .errors import AppError
from .tts import Word, validate_words
from .voices import KOKORO_VOICES

MODEL_REPO = "hexgrad/Kokoro-82M"
MODEL_REVISION = "f3ff3571791e39611d31c381e3a41a3af07b4987"
SAMPLE_RATE = 24000


def token_words(tokens, offset: float, duration: float) -> list[Word]:
    """Group subword/contraction tokens by whitespace, never estimate word durations."""
    words, text = [], ""
    start = end = None
    for token in tokens or []:
        text += token.text
        if any(c.isalnum() for c in token.text):
            left, right = token.start_ts, token.end_ts
            if left is None or right is None or not token.phonemes:
                raise AppError(
                    "Kokoro returned a spoken token without timestamps; export rejected."
                )
            start = float(left) if start is None else start
            end = float(right)
        if token.whitespace:
            if start is not None:
                if len(text.split()) != 1:
                    raise AppError(
                        "Kokoro returned phrase-level timing instead of individual words."
                    )
                words.append(Word(text, start, end))
            text, start, end = "", None, None
    if start is not None:
        if len(text.split()) != 1:
            raise AppError("Kokoro returned phrase-level timing instead of individual words.")
        words.append(Word(text, start, end))
    validate_words(words, duration)
    return [Word(word.text, offset + word.start, offset + word.end) for word in words]


class KokoroNarrator:
    audio_suffix = ".wav"

    def __init__(self, voice: str, rate: str, cache: Path):
        if voice not in KOKORO_VOICES:
            raise AppError(
                "Unsupported Kokoro voice. Use 'voices --engine kokoro' for British voices."
            )
        self.voice, self.rate, self.cache = voice, rate, cache.resolve()
        self._pipeline = self._voice_path = None

    def _load(self):
        if self._pipeline is not None:
            return
        # These affect only this CLI process, not Windows/Linux user settings. Set before
        # importing HF so downloads, optional library caches and telemetry stay scoped.
        self.cache.mkdir(parents=True, exist_ok=True)
        os.environ["HF_HOME"] = str(self.cache)
        os.environ["HF_XET_CACHE"] = str(self.cache / "xet")
        os.environ["HF_HUB_DISABLE_XET"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["TORCH_HOME"] = str(self.cache / "torch")
        try:
            import espeakng_loader
            import spacy
            import torch
            from huggingface_hub import hf_hub_download
            from phonemizer.backend.espeak.wrapper import EspeakWrapper

            if not spacy.util.is_package("en_core_web_sm"):
                raise AppError("Install the English model: python -m spacy download en_core_web_sm")
            EspeakWrapper.set_library(espeakng_loader.get_library_path())
            EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
            from kokoro import KModel, KPipeline

            def asset(filename):
                return hf_hub_download(
                    MODEL_REPO,
                    filename,
                    revision=MODEL_REVISION,
                    cache_dir=str(self.cache / "hub"),
                    token=False,
                )

            config = asset("config.json")
            weights = asset("kokoro-v1_0.pth")
            voice_path = asset(f"voices/{self.voice}.pt")
            # More threads can make short CPU utterances slower; no GPU is required.
            torch.set_num_threads(min(4, os.cpu_count() or 1))
            model = KModel(repo_id=MODEL_REPO, config=config, model=weights).to("cpu").eval()
            pipeline = KPipeline(lang_code="b", repo_id=MODEL_REPO, model=model)
            if pipeline.g2p.fallback is None:
                raise AppError(
                    "Kokoro's pronunciation fallback could not load; check espeakng-loader."
                )
            self._pipeline, self._voice_path = pipeline, voice_path
        except ImportError as exc:
            raise AppError(
                "Local voice dependencies are missing. Install: pip install -e '.[kokoro]'"
            ) from exc
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                f"Cannot initialize local Kokoro ({type(exc).__name__}). Check the local voice "
                "installation and internet access for the first model download. See README."
            ) from exc

    def synthesize(self, text: str, destination: Path) -> list[Word]:
        if not text.strip():
            raise AppError("The post contains no readable narration text.")
        self._load()
        try:
            import numpy as np
            import soundfile as sf

            words, frames = [], 0
            speed = 1 + int(self.rate[:-1]) / 100
            with sf.SoundFile(
                str(destination),
                mode="w",
                samplerate=SAMPLE_RATE,
                channels=1,
                format="WAV",
                subtype="PCM_16",
            ) as output:
                for result in self._pipeline(text, voice=self._voice_path, speed=speed):
                    if result.audio is None:
                        raise AppError("Kokoro returned no audio.")
                    samples = np.asarray(result.audio, dtype=np.float32)
                    if samples.ndim != 1 or not samples.size or not np.isfinite(samples).all():
                        raise AppError("Kokoro returned invalid audio.")
                    words.extend(
                        token_words(result.tokens, frames / SAMPLE_RATE, samples.size / SAMPLE_RATE)
                    )
                    output.write(samples)
                    frames += samples.size
            validate_words(words, frames / SAMPLE_RATE)
            return words
        except BaseException as exc:
            with suppress(OSError):
                destination.unlink(missing_ok=True)
            if isinstance(exc, (AppError, KeyboardInterrupt, SystemExit)):
                raise
            raise AppError(
                f"Local speech generation failed ({type(exc).__name__}); export rejected."
            ) from exc
