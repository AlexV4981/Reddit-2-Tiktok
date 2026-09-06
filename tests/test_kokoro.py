import os
import wave
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from reddit2tiktok.errors import AppError
from reddit2tiktok.kokoro_tts import KokoroNarrator, token_words
from reddit2tiktok.media import Media, run
from reddit2tiktok.pipeline import Pipeline
from reddit2tiktok.store import Store
from reddit2tiktok.tts import Word, create_narrator, validate_words


def token(text, start=0.1, end=0.4, whitespace=" ", phonemes="test"):
    return SimpleNamespace(
        text=text, start_ts=start, end_ts=end, whitespace=whitespace, phonemes=phonemes
    )


def test_local_word_offsets_include_real_previous_chunk_audio_and_join_contractions():
    tokens = [
        token("Hello", whitespace=""),
        token(",", None, None),
        token("could", 0.6, 0.8, whitespace=""),
        token("n't", 0.8, 1.0),
    ]
    assert token_words(tokens, 5.0, 1.5) == [Word("Hello,", 5.1, 5.4), Word("couldn't", 5.6, 6.0)]


@pytest.mark.parametrize(
    "tokens",
    [
        [],
        [token("word", None, None)],
        [token("word", -1, 0.5)],
        [token("word", 0.1, 3)],
        [token("two words")],
        [token("word", phonemes="")],
    ],
)
def test_local_missing_or_invalid_timing_never_gets_estimated(tokens):
    with pytest.raises(AppError):
        token_words(tokens, 0, 1)
    with pytest.raises(AppError):
        token_words(tokens, 10, 1)


def test_narrator_factory_does_not_load_models_before_rendering(config, tmp_path):
    configured = replace(config, tts_engine="kokoro", voice="bm_daniel")
    narrator = create_narrator(configured, tmp_path / "config.json")
    assert isinstance(narrator, KokoroNarrator)
    assert narrator.cache == tmp_path / "data" / "tts-cache"
    assert narrator._pipeline is None
    assert not narrator.cache.exists()


@pytest.fixture(scope="module")
def local_narrator(tmp_path_factory):
    if os.environ.get("R2T_REQUIRE_LOCAL_TTS") != "1":
        pytest.skip("Set R2T_REQUIRE_LOCAL_TTS=1 for real local speech tests")
    cache = Path(os.environ.get("R2T_KOKORO_CACHE", str(tmp_path_factory.mktemp("kokoro-cache"))))
    return KokoroNarrator("bm_daniel", "+0%", cache)


@pytest.mark.local_tts
def test_real_local_speech_multi_chunk_word_timing(local_narrator, tmp_path):
    sentence = "This ordinary story has a beginning and a happy ending."
    text = "Hello there.\n\n" + " ".join([sentence] * 10)
    path = tmp_path / "speech.wav"
    words = local_narrator.synthesize(text, path)
    with wave.open(str(path)) as audio:
        assert audio.getframerate() == 24000 and audio.getnchannels() == 1
        duration = audio.getnframes() / audio.getframerate()
        assert any(audio.readframes(audio.getnframes()))
    validate_words(words, duration)
    assert [w.text for w in words] == text.split()
    assert words[-1].end > 10
    assert duration - words[-1].end < 1


@pytest.mark.local_tts
@pytest.mark.integration
def test_real_local_voice_renders_narrated_and_silent_pair(
    config, tmp_path, post, media_tools, local_narrator
):
    ffmpeg, ffprobe = media_tools
    config = replace(config, tts_engine="kokoro", voice="bm_daniel", ffmpeg=ffmpeg, ffprobe=ffprobe)
    run(
        [
            ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=360x640:r=24:d=20",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(Path(config.video_dir) / "background.mp4"),
        ]
    )
    store = Store(tmp_path / "data" / "posts.sqlite3")
    store.save([post])
    result = Pipeline(config, tmp_path / "config.json", store, local_narrator).render([post.id])
    assert result.ready == 1 and result.failed == 0
    row = store.get(post.id)
    media = Media(config)
    voiced, silent = Path(row["output_path"]), Path(row["silent_output_path"])
    assert voiced.name == "with_voice.mp4" and silent.name == "without_voice.mp4"
    voiced_info, silent_info = media.probe(voiced), media.probe(silent)
    assert any(s["codec_type"] == "audio" for s in voiced_info["streams"])
    assert not any(s["codec_type"] == "audio" for s in silent_info["streams"])
    assert media.duration(voiced_info, "video") == media.duration(silent_info, "video")
    assert run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(voiced),
            "-map",
            "0:v:0",
            "-c:v",
            "copy",
            "-f",
            "hash",
            "-",
        ]
    ) == run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(silent),
            "-map",
            "0:v:0",
            "-c:v",
            "copy",
            "-f",
            "hash",
            "-",
        ]
    )
