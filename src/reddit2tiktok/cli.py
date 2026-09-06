from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from dataclasses import asdict, replace
from pathlib import Path

from selenium.common.exceptions import WebDriverException

from . import __version__
from .browser import open_browser
from .config import Config, load_config, resolve_path, save_config
from .errors import AppError
from .media import Media
from .pipeline import Pipeline
from .reddit import RedditClient, subreddit_name
from .store import Store, outputs_exist
from .text import terminal_text
from .tts import available_voices, create_narrator, validate_words
from .voices import KOKORO_VOICES, default_voice


def wizard(path: Path, existing: Config | None = None) -> Config:
    print("\nReddit → TikTok configuration")
    print("Verbose lists titles and links. Normal mode lists titles only.")
    default = existing.verbose if existing else False
    while True:
        answer = input(f"Verbose? [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        if answer in {"", "y", "yes", "n", "no"}:
            verbose = default if not answer else answer in {"y", "yes"}
            break
        print("Enter y or n.")
    while True:
        previous = existing.video_dir if existing else ""
        answer = input(f"Background videos folder{f' [{previous}]' if previous else ''}: ").strip()
        value = answer or previous
        if value and resolve_path(value, path).is_dir():
            video_dir = str(resolve_path(value, path))
            break
        print("Enter an existing folder containing your background videos.")
    voice = existing.voice if existing else "bm_daniel"
    print("Local Kokoro British Daniel is the default; its first use downloads model files.")
    print("An Edge voice ID, such as en-GB-RyanNeural, selects the optional online engine.")
    voice = input(f"Voice ID [{voice}]: ").strip() or voice
    engine = "kokoro" if voice.startswith(("bm_", "bf_")) else "edge"
    config = (
        replace(existing, verbose=verbose, video_dir=video_dir, voice=voice, tts_engine=engine)
        if existing
        else (Config(video_dir=video_dir, verbose=verbose, voice=voice, tts_engine=engine))
    )
    save_config(path, config)
    print(f"Saved configuration: {path}")
    return config


def print_posts(rows: list[dict], verbose: bool, *, details: bool = False) -> None:
    if not rows:
        print("No scraped posts yet.")
        return
    for row in rows:
        print(terminal_text(row["title"]))
        if verbose:
            print(row["url"])
        if details:
            print(f"  {row['id']} | {row['status']}")
            if row["output_path"]:
                print(f"  {row['output_path']}")
            if row.get("silent_output_path"):
                print(f"  {row['silent_output_path']}")
            if row["error"]:
                print(f"  {terminal_text(row['error'])}")


def scrape(config: Config, path: Path, store: Store, name: str, scrape_only: bool = False) -> int:
    name = subreddit_name(name)
    print(f"Fetching the top 10 posts this week from r/{name}...")
    print("Starting Selenium Chrome (the first run may download Chrome and its driver)...")
    posts = RedditClient(config, path).top_week(name)
    added = store.save(posts)
    print(f"Fetched {len(posts)} posts; saved {added} new posts.")
    if not posts:
        return 0
    if scrape_only:
        print_posts([store.get(post.id) for post in posts], config.verbose)
        return 0
    result = Pipeline(config, path, store).render([post.id for post in posts])
    print(f"Finished: {result.ready} ready, {result.skipped} skipped, {result.failed} failed.")
    return 1 if result.failed else 0


def pending_ids(store: Store, force: bool = False) -> list[str]:
    return [
        row["id"]
        for row in store.all()
        if force
        or row["status"]
        in {
            "scraped",
            "failed",
            "rendering",
        }
        or (row["status"] == "ready" and not outputs_exist(row))
    ]


def render(
    config: Config, path: Path, store: Store, post_id: str | None, force: bool = False
) -> int:
    ids = [post_id] if post_id else pending_ids(store, force)
    if not ids:
        print("No unfinished posts to render.")
        return 0
    result = Pipeline(config, path, store).render(ids, force=force)
    print(f"Finished: {result.ready} ready, {result.skipped} skipped, {result.failed} failed.")
    return 1 if result.failed else 0


def menu(config: Config, path: Path) -> int:
    while True:
        print(
            "\nReddit → TikTok\n1) Scrape + create videos\n2) Config\n"
            "3) Show all scraped posts\n4) Retry unfinished videos\n0) Exit"
        )
        choice = input("Choose: ").strip()
        try:
            store = Store(resolve_path(config.data_dir, path) / "posts.sqlite3")
            if choice == "0":
                return 0
            if choice == "1":
                scrape(config, path, store, input("Subreddit: "))
            elif choice == "2":
                config = wizard(path, config)
            elif choice == "3":
                print_posts(store.all(), config.verbose)
            elif choice == "4":
                render(config, path, store, None)
            else:
                print("Choose 0, 1, 2, 3, or 4.")
        except (AppError, OSError, sqlite3.Error) as exc:
            print(f"Error: {terminal_text(str(exc))}", file=sys.stderr)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Create captioned Reddit story videos on Linux.")
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument(
        "--config",
        type=Path,
        default=Path("config.json"),
        metavar="FILE",
        help="configuration file (default: ./config.json)",
    )
    verbosity = root.add_mutually_exclusive_group()
    verbosity.add_argument("--verbose", action="store_true", default=None, help="show post links")
    verbosity.add_argument("--quiet", dest="verbose", action="store_false", help="hide post links")
    commands = root.add_subparsers(dest="command")
    config = commands.add_parser("config", help="first-run setup or edit configuration")
    config.add_argument("--video-dir", help="set the explicit input folder without prompts")
    config.add_argument("--voice", help="voice ID, default local bm_daniel")
    config.add_argument(
        "--tts-engine", choices=["kokoro", "edge"], help="local or online speech engine"
    )
    config.add_argument(
        "--browser-binary", help="path to Chrome/Chromium, or empty for managed Chrome"
    )
    config.add_argument("--chromedriver", help="path to a matching ChromeDriver")
    config.add_argument(
        "--browser-remote-url", help="private Selenium Grid URL, or empty for local"
    )
    config.add_argument("--reddit-frontend", choices=["old", "www"], help="Reddit HTML interface")
    config.add_argument(
        "--rate", help="speech rate, for example +10%% (use --rate=-10%% for negative)"
    )
    config.add_argument("--show", action="store_true", help="print current configuration")
    scrape_cmd = commands.add_parser("scrape", help="fetch this week's top 10 and create videos")
    scrape_cmd.add_argument("subreddit", nargs="?")
    scrape_cmd.add_argument(
        "--scrape-only", action="store_true", help="save posts without rendering"
    )
    posts = commands.add_parser("posts", help="show all saved posts")
    posts.add_argument("--details", action="store_true", help="also show IDs, statuses and errors")
    posts.add_argument("--json", action="store_true", help="export full records as JSON")
    rendering = commands.add_parser("render", help="render unfinished posts, or one specific ID")
    rendering.add_argument("post_id", nargs="?")
    rendering.add_argument(
        "--force", action="store_true", help="create new versions of completed videos"
    )
    doctor = commands.add_parser("doctor", help="check local media tools and background videos")
    doctor.add_argument(
        "--browser", action="store_true", help="also launch and verify Selenium Chrome"
    )
    voices = commands.add_parser("voices", help="list local Kokoro or online Edge voices")
    voices.add_argument("--engine", choices=["kokoro", "edge"], default="kokoro")
    voices.add_argument("--locale", default="en-GB")
    commands.add_parser("voice-test", help="generate a short narration and check its word timings")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    path = args.config.expanduser().resolve()
    try:
        if args.command == "voices":
            if args.engine == "kokoro":
                if args.locale.lower() == "en-gb":
                    for identity, description in KOKORO_VOICES.items():
                        print(f"{identity} ({description})")
                return 0
            voices = asyncio.run(available_voices())
            for voice in voices:
                if voice["Locale"].lower() == args.locale.lower():
                    print(f"{voice['ShortName']} ({voice['Gender']})")
            return 0
        config = load_config(path) if path.exists() else None
        if args.command == "config":
            if args.show:
                if config is None:
                    raise AppError("No configuration yet. Run the config command first.")
                print(json.dumps(asdict(config), indent=2))
                return 0
            config_keys = (
                "video_dir",
                "voice",
                "tts_engine",
                "rate",
                "verbose",
                "browser_binary",
                "chromedriver",
                "browser_remote_url",
                "reddit_frontend",
            )
            if any(getattr(args, key) is not None for key in config_keys):
                if config is None and not args.video_dir:
                    raise AppError("First configuration requires --video-dir /path/to/videos.")
                config = config or Config(video_dir=args.video_dir)
                changes = {
                    key: getattr(args, key) for key in config_keys if getattr(args, key) is not None
                }
                if "tts_engine" in changes and "voice" not in changes:
                    changes["voice"] = default_voice(changes["tts_engine"])
                elif "voice" in changes and "tts_engine" not in changes:
                    changes["tts_engine"] = (
                        "kokoro" if changes["voice"].startswith(("bm_", "bf_")) else "edge"
                    )
                if "video_dir" in changes:
                    changes["video_dir"] = str(resolve_path(changes["video_dir"], path))
                config = replace(config, **changes)
                if not resolve_path(config.video_dir, path).is_dir():
                    raise AppError("The background videos folder must already exist.")
                save_config(path, config)
                print(f"Saved configuration: {path}")
            elif sys.stdin.isatty():
                wizard(path, config)
            else:
                raise AppError(
                    "Interactive setup needs a terminal. Use config --video-dir /path/to/videos."
                )
            return 0
        if config is None:
            if not sys.stdin.isatty():
                raise AppError(
                    "Run reddit2tiktok config --video-dir /path/to/videos before unattended use."
                )
            config = wizard(path)
        if args.verbose is not None:
            config = replace(config, verbose=args.verbose)
        if args.command == "voice-test":
            narrator = create_narrator(config, path)
            folder = resolve_path(config.data_dir, path) / "voice-test"
            folder.mkdir(parents=True, exist_ok=True)
            audio = folder / f"narration{narrator.audio_suffix}"
            print(
                f"Testing {config.tts_engine}/{config.voice}; the first local run downloads model files..."
            )
            words = narrator.synthesize(
                "Hello there. This is a story voice test. The captions follow each word.",
                audio,
            )
            duration = Media(config, path).duration(Media(config, path).probe(audio), "audio")
            validate_words(words, duration)
            (folder / "words.json").write_text(
                json.dumps([asdict(w) for w in words], indent=2), encoding="utf-8"
            )
            print(f"Voice OK: {len(words)} timed words, {duration:.2f}s. Audio: {audio}")
            return 0
        if args.command is None:
            if not sys.stdin.isatty():
                raise AppError("The menu needs a terminal. Use scrape, posts, render, or doctor.")
            return menu(config, path)
        if args.command == "doctor":
            media = Media(config, path)
            media.check_tools()
            videos, warnings = media.backgrounds(resolve_path(config.video_dir, path))
            for warning in warnings:
                print(terminal_text(warning))
            print(f"FFmpeg, libass, H.264 and AAC OK; {len(videos)} readable background videos.")
            print(f"Longest background: {max(v.duration for v in videos):.1f}s")
            if args.browser:
                with open_browser(config, path) as driver:
                    driver.get("data:text/html,<title>Browser check</title>")
                    if driver.title != "Browser check":
                        raise AppError("Selenium Chrome did not load the browser check page.")
                    print(f"Selenium Chrome {driver.capabilities.get('browserVersion', '')} OK.")
            print(f"Voice: {config.tts_engine}/{config.voice}. Run voice-test to verify speech.")
            return 0
        store = Store(resolve_path(config.data_dir, path) / "posts.sqlite3")
        if args.command == "posts":
            rows = store.all()
            if args.json:
                print(json.dumps(rows, indent=2, ensure_ascii=False))
            else:
                print_posts(rows, config.verbose, details=args.details)
            return 0
        if args.command == "render":
            return render(config, path, store, args.post_id, args.force)
        if args.command == "scrape":
            name = args.subreddit
            if not name:
                if not sys.stdin.isatty():
                    raise AppError("Provide a subreddit for unattended scraping.")
                name = input("Subreddit: ")
            return scrape(config, path, store, name, args.scrape_only)
        return 0
    except WebDriverException:
        print(
            "Error: Selenium Chrome failed. Check browser setup with doctor --browser.",
            file=sys.stderr,
        )
        return 1
    except (AppError, OSError, sqlite3.Error, ValueError) as exc:
        print(f"Error: {terminal_text(str(exc))}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nStopped. Saved posts remain available for retry.", file=sys.stderr)
        return 130
