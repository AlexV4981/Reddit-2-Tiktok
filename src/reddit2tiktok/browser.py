"""An isolated Selenium browser for each scrape, with deterministic cleanup."""

from __future__ import annotations

import tempfile
from contextlib import contextmanager, suppress
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.selenium_manager import SeleniumManager
from selenium.webdriver.remote.client_config import ClientConfig
from urllib3.exceptions import HTTPError

from .config import Config, resolve_path
from .errors import AppError


def browser_paths(config: Config, config_file: Path) -> tuple[str, str]:
    """Use explicit binaries or let Selenium Manager provision a matching pair."""
    binary = str(resolve_path(config.browser_binary, config_file)) if config.browser_binary else ""
    driver = str(resolve_path(config.chromedriver, config_file)) if config.chromedriver else ""
    for value in (binary, driver):
        if value and not Path(value).is_file():
            raise AppError(f"Configured browser executable does not exist: {value}")
    if driver and binary:
        return binary, driver
    if driver:
        raise AppError(
            "When setting chromedriver, also set browser_binary to the matching browser."
        )
    cache = resolve_path(config.data_dir, config_file) / "browser-cache"
    cache.mkdir(parents=True, exist_ok=True)
    arguments = [
        "--browser",
        "chrome",
        "--cache-path",
        str(cache),
        "--avoid-stats",
        "--skip-driver-in-path",
        "--timeout",
        "120",
    ]
    if binary:
        arguments += ["--browser-path", binary]
    else:
        arguments += ["--browser-version", "stable", "--force-browser-download"]
    try:
        result = SeleniumManager().binary_paths(arguments)
        return binary or result["browser_path"], driver or result["driver_path"]
    except (WebDriverException, KeyError) as exc:
        raise AppError(
            "Cannot provision Chrome/ChromeDriver. Check internet access or set browser_binary "
            "and chromedriver to a matching, locally installed pair in config."
        ) from exc


@contextmanager
def open_browser(config: Config, config_file: Path):
    if config.browser_remote_url:
        with remote_browser(config) as driver:
            yield driver
        return
    binary, executable = browser_paths(config, config_file)
    profiles = resolve_path(config.data_dir, config_file) / "browser-profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    driver = None
    service = Service(executable_path=executable)
    with tempfile.TemporaryDirectory(prefix="scrape-", dir=profiles) as profile:
        options = webdriver.ChromeOptions()
        options.binary_location = binary
        if config.browser_headless:
            options.add_argument("--headless=new")
        for flag in (
            "--window-size=1280,1000",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile}",
        ):
            options.add_argument(flag)
        try:
            driver = webdriver.Chrome(service=service, options=options)
            driver.set_page_load_timeout(config.browser_timeout)
            driver.set_script_timeout(config.browser_timeout)
            driver.implicitly_wait(0)
        except WebDriverException as exc:
            if driver is not None:
                with suppress(WebDriverException):
                    driver.quit()
            service.stop()
            raise AppError(
                "Chrome could not start. Check matching Chrome/ChromeDriver versions and Linux "
                "browser libraries. Run as a regular user with Chrome's sandbox available. "
                "Use 'doctor --browser' to check browser startup."
            ) from exc
        try:
            yield driver
        finally:
            with suppress(WebDriverException):
                driver.quit()
            service.stop()


@contextmanager
def remote_browser(config: Config):
    """One fresh anonymous Grid session; no host profile, cookies or files are uploaded."""
    config.validate()
    options = webdriver.ChromeOptions()
    if config.browser_headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1280,1000")
    driver = None
    try:
        driver = webdriver.Remote(
            command_executor=config.browser_remote_url,
            options=options,
            client_config=ClientConfig(
                remote_server_addr=config.browser_remote_url,
                timeout=max(60, config.browser_timeout + 10),
            ),
        )
        driver.set_page_load_timeout(config.browser_timeout)
        driver.set_script_timeout(config.browser_timeout)
        driver.implicitly_wait(0)
        yield driver
    except (WebDriverException, HTTPError, OSError) as exc:
        raise AppError(
            "Remote Selenium failed. Check the browser container with 'docker compose ps' "
            "and retry 'doctor --browser'. No personal browser session is reused."
        ) from exc
    finally:
        if driver is not None:
            with suppress(WebDriverException, HTTPError, OSError):
                driver.quit()
