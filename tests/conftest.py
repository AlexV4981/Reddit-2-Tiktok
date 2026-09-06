import os
import shutil
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from reddit2tiktok.browser import browser_paths
from reddit2tiktok.config import Config
from reddit2tiktok.reddit import Post


@pytest.fixture
def config(tmp_path):
    videos = tmp_path / "background clips"
    videos.mkdir()
    return Config(
        video_dir=str(videos), width=360, height=640, fps=24, font_size=40, preset="ultrafast"
    )


@pytest.fixture
def post():
    return Post(
        "abc123",
        "stories",
        "An ordinary day",
        "Then something surprising happened.",
        "https://www.reddit.com/r/stories/comments/abc123/an_ordinary_day/",
        42,
        100.0,
    )


@pytest.fixture
def media_tools():
    ffmpeg = shutil.which(os.environ.get("R2T_FFMPEG", "ffmpeg"))
    ffprobe = shutil.which(os.environ.get("R2T_FFPROBE", "ffprobe"))
    if not ffmpeg or not ffprobe:
        if os.environ.get("R2T_REQUIRE_FFMPEG") == "1":
            pytest.fail("FFmpeg/ffprobe are required for this test run")
        pytest.skip("FFmpeg/ffprobe not installed")
    return str(Path(ffmpeg).resolve()), str(Path(ffprobe).resolve())


@pytest.fixture(scope="session")
def browser_binaries(tmp_path_factory):
    binary = os.environ.get("R2T_CHROME_BINARY", "")
    driver = os.environ.get("R2T_CHROMEDRIVER", "")
    if not (binary and driver) and os.environ.get("R2T_REQUIRE_BROWSER") != "1":
        pytest.skip("Set R2T_REQUIRE_BROWSER=1 or provide Chrome and ChromeDriver paths")
    folder = tmp_path_factory.mktemp("browser")
    return browser_paths(
        Config(video_dir=str(folder), browser_binary=binary, chromedriver=driver),
        folder / "config.json",
    )


@pytest.fixture
def browser_config(config, browser_binaries):
    binary, driver = browser_binaries
    return replace(
        config, browser_binary=binary, chromedriver=driver, scrape_delay=0, browser_timeout=5
    )


@pytest.fixture
def html_server():
    routes, visits = {}, []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            visits.append(self.path)
            page = routes.get(self.path)
            self.send_response(200 if page is not None else 404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write((page or "Not found").encode("utf-8"))

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", routes, visits
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
