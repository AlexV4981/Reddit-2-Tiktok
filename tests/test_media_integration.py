"""Offline end-to-end media checks using real FFmpeg, rather than mocked encoders."""

import array
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from reddit2tiktok.captions import write_ass
from reddit2tiktok.cli import main
from reddit2tiktok.config import save_config
from reddit2tiktok.media import Background, Media, run
from reddit2tiktok.reddit import RedditClient
from reddit2tiktok.store import Store
from reddit2tiktok.tts import Word
from tests.html_pages import delayed, legacy_card


@pytest.mark.integration
@pytest.mark.parametrize("offset", [0.001, 0.02, 0.04, 1.234])
@pytest.mark.parametrize("preset", ["ultrafast", "medium"])
def test_fractional_seek_preserves_zero_origin_and_silent_packet_timing(
    config, tmp_path, media_tools, offset, preset
):
    ffmpeg, ffprobe = media_tools
    config = replace(config, ffmpeg=ffmpeg, ffprobe=ffprobe, preset=preset)
    media = Media(config)
    background, audio = tmp_path / "source.mp4", tmp_path / "speech.wav"
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
            "color=c=blue:s=360x640:r=24:d=6",
            "-c:v",
            "libx264",
            str(background),
        ]
    )
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
            "sine=frequency=440:duration=4.65:sample_rate=24000",
            str(audio),
        ]
    )
    subtitles = tmp_path / "captions.ass"
    write_ass([Word("Timing", 0.2, 1.0)], subtitles, config, 4.65)
    voiced, silent = tmp_path / "with_voice.mp4", tmp_path / "without_voice.mp4"
    media.render(Background(background, 6), offset, audio, subtitles, voiced, 4.65)
    media.silent_copy(voiced, silent, 4.65)
    video_streams = []
    packet_sets, hashes = [], []
    for path in (voiced, silent):
        video_streams.append(
            next(s for s in media.probe(path)["streams"] if s["codec_type"] == "video")
        )
        packet_sets.append(
            json.loads(
                run(
                    [
                        ffprobe,
                        "-v",
                        "error",
                        "-select_streams",
                        "v:0",
                        "-show_packets",
                        "-show_entries",
                        "packet=pts_time,dts_time,duration_time,size",
                        "-of",
                        "json",
                        str(path),
                    ]
                )
            )["packets"]
        )
        hashes.append(
            run(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-i",
                    str(path),
                    "-map",
                    "0:v:0",
                    "-c:v",
                    "copy",
                    "-f",
                    "hash",
                    "-",
                ]
            )
        )
    assert all(float(s["start_time"]) == 0 for s in video_streams)
    assert video_streams[0]["duration"] == video_streams[1]["duration"]
    assert packet_sets[0] == packet_sets[1]
    assert hashes[0] == hashes[1]


@pytest.mark.integration
@pytest.mark.parametrize("source", ["mock", pytest.param("selenium", marks=pytest.mark.browser)])
def test_real_scrape_render_captions_audio_and_dedup(
    config,
    tmp_path,
    post,
    media_tools,
    monkeypatch,
    capsys,
    source,
    request,
    html_server,
):
    ffmpeg, ffprobe = media_tools
    if source == "selenium":
        config = request.getfixturevalue("browser_config")
    config = replace(config, ffmpeg=ffmpeg, ffprobe=ffprobe)
    config_file = tmp_path / "config.json"
    save_config(config_file, config)
    # Spaces, apostrophes and brackets in paths must never enter an FFmpeg filter expression.
    folder = Path(config.video_dir) / "story's [clips]"
    folder.mkdir()
    background = folder / "blue.mp4"
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x172338:s=640x360:r=24:d=4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:duration=4",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(background),
        ]
    )
    calls = []

    def synthesize(self, text, audio):
        calls.append(text)
        run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=880:duration=1.5:sample_rate=24000",
                "-c:a",
                "libmp3lame",
                str(audio),
            ]
        )
        return [Word("Hello", 0.1, 0.5), Word("again", 0.9, 1.3)]

    monkeypatch.setattr("reddit2tiktok.tts.EdgeNarrator.synthesize", synthesize)
    if source == "selenium":
        base, routes, _ = html_server
        routes["/r/stories/top/?t=week&limit=10"] = delayed(legacy_card(post.id, title=post.title))
        routes[f"/r/stories/comments/{post.id}/story/"] = delayed(
            legacy_card(post.id, post.body, title=post.title)
        )
        monkeypatch.setattr(
            "reddit2tiktok.cli.RedditClient",
            lambda config, file: RedditClient(config, file, base_url=base),
        )
    else:
        monkeypatch.setattr("reddit2tiktok.cli.RedditClient.top_week", lambda self, name: [post])
    args = ["--config", str(config_file), "scrape", "stories"]
    assert main(args) == 0
    store = Store(tmp_path / "data" / "posts.sqlite3")
    row = store.get(post.id)
    assert row["status"] == "ready"
    assert row["body"] == post.body
    assert post.title in calls[0] and post.body in calls[0]
    final = Path(row["output_path"])
    silent = Path(row["silent_output_path"])
    assert final.parent == silent.parent
    assert final.name == "with_voice.mp4" and silent.name == "without_voice.mp4"
    media = Media(config)
    info = media.probe(final)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert (video["width"], video["height"]) == (360, 640)
    assert video["codec_name"] == "h264"
    assert audio["codec_name"] == "aac"
    assert video["pix_fmt"] == "yuv420p"
    assert video["avg_frame_rate"] == "24/1"
    silent_info = media.probe(silent)
    assert not any(s["codec_type"] == "audio" for s in silent_info["streams"])
    assert media.duration(silent_info, "video") == media.duration(info, "video")

    def video_hash(path):
        return run(
            [
                ffmpeg,
                "-v",
                "error",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-c:v",
                "copy",
                "-f",
                "hash",
                "-",
            ]
        )

    assert video_hash(final) == video_hash(silent)
    manifest = json.loads(
        next((tmp_path / "data" / "artifacts").glob("*/manifest.json")).read_text()
    )
    assert abs(media.duration(info, "video") - manifest["duration"]) < 0.15
    assert abs(media.duration(info, "audio") - manifest["duration"]) < 0.15
    assert 0 <= manifest["start"] <= 4 - manifest["duration"]

    def yellow_pixels(at):
        frame = subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-ss",
                str(at),
                "-i",
                str(final),
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ],
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout
        assert len(frame) == config.width * config.height * 3
        return sum(
            r > 160 and g > 160 and b < 120
            for r, g, b in zip(frame[0::3], frame[1::3], frame[2::3], strict=True)
        )

    assert yellow_pixels(0.3) > 100  # first word burned in
    assert yellow_pixels(0.7) == 0  # actual pause, no caption
    assert yellow_pixels(1.1) > 100  # next word burned in

    # Narration is 880Hz; the source clip's 220Hz sound must not leak into the result.
    pcm = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-ss",
            "0.2",
            "-i",
            str(final),
            "-t",
            "0.5",
            "-vn",
            "-f",
            "s16le",
            "-ar",
            "8000",
            "-ac",
            "1",
            "-",
        ],
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout
    samples = array.array("h", pcm)
    crossings = sum(a < 0 <= b for a, b in zip(samples[:-1], samples[1:], strict=True))
    frequency = crossings / (len(samples) / 8000)
    assert 850 < frequency < 910
    assert main(args) == 0
    assert len(calls) == 1
    assert len(list((tmp_path / "ready4upload").rglob("*.mp4"))) == 2
    assert "Already ready" in capsys.readouterr().out


@pytest.mark.integration
def test_real_probe_rejects_corrupt_background_but_keeps_valid(config, tmp_path, media_tools):
    ffmpeg, ffprobe = media_tools
    config = replace(config, ffmpeg=ffmpeg, ffprobe=ffprobe)
    folder = Path(config.video_dir)
    (folder / "broken.mp4").write_bytes(b"not a video")
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
            "color=c=black:s=160x90:r=10:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(folder / "valid.mp4"),
        ]
    )
    media = Media(config)
    media.check_tools()
    videos, warnings = media.backgrounds(folder)
    assert len(videos) == 1
    assert videos[0].path.name == "valid.mp4"
    assert 0.9 < videos[0].duration < 1.1
    assert warnings == ["Ignoring unreadable background: broken.mp4"]
