from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from selenium.common.exceptions import WebDriverException

from reddit2tiktok.browser import browser_paths, open_browser
from reddit2tiktok.errors import AppError


def test_explicit_binaries_resolve_beside_config(config, tmp_path, monkeypatch):
    for name in ("chrome", "driver"):
        (tmp_path / name).touch()
    manager = MagicMock()
    monkeypatch.setattr("reddit2tiktok.browser.SeleniumManager", manager)
    configured = replace(config, browser_binary="chrome", chromedriver="driver")
    assert browser_paths(configured, tmp_path / "config.json") == (
        str(tmp_path / "chrome"),
        str(tmp_path / "driver"),
    )
    manager.assert_not_called()


def test_managed_chrome_cache_stays_in_data_folder(config, tmp_path, monkeypatch):
    manager = MagicMock()
    manager.return_value.binary_paths.return_value = {
        "browser_path": "chrome",
        "driver_path": "driver",
    }
    monkeypatch.setattr("reddit2tiktok.browser.SeleniumManager", manager)
    assert browser_paths(config, tmp_path / "config.json") == ("chrome", "driver")
    args = manager.return_value.binary_paths.call_args.args[0]
    assert args[args.index("--cache-path") + 1] == str(tmp_path / "data" / "browser-cache")
    assert "--force-browser-download" in args
    assert "--avoid-stats" in args


def test_provision_failure_has_manual_install_guidance(config, tmp_path, monkeypatch):
    manager = MagicMock()
    manager.return_value.binary_paths.side_effect = WebDriverException("offline")
    monkeypatch.setattr("reddit2tiktok.browser.SeleniumManager", manager)
    with pytest.raises(AppError, match="matching, locally installed pair"):
        browser_paths(config, tmp_path / "config.json")
    with pytest.raises(AppError, match="does not exist"):
        browser_paths(replace(config, browser_binary="missing"), tmp_path / "config.json")


@pytest.mark.parametrize("fail", [False, True])
def test_session_is_isolated_headless_and_cleaned_up(config, tmp_path, monkeypatch, fail):
    monkeypatch.setattr("reddit2tiktok.browser.browser_paths", lambda *a: ("chrome", "driver"))
    constructor, service = MagicMock(), MagicMock()
    monkeypatch.setattr("reddit2tiktok.browser.webdriver.Chrome", constructor)
    monkeypatch.setattr("reddit2tiktok.browser.Service", service)
    try:
        with open_browser(config, tmp_path / "config.json") as driver:
            assert driver is constructor.return_value
            options = constructor.call_args.kwargs["options"]
            assert "--headless=new" in options.arguments
            assert "--no-sandbox" not in options.arguments
            profile = Path(
                next(
                    a.split("=", 1)[1]
                    for a in options.arguments
                    if a.startswith("--user-data-dir=")
                )
            )
            assert profile.is_dir()
            assert profile.parent == tmp_path / "data" / "browser-profiles"
            if fail:
                raise ValueError("fixture error")
    except ValueError:
        assert fail
    assert not profile.exists()
    constructor.return_value.quit.assert_called_once()
    service.return_value.stop.assert_called_once()


def test_failed_start_stops_service_and_removes_profile(config, tmp_path, monkeypatch):
    monkeypatch.setattr("reddit2tiktok.browser.browser_paths", lambda *a: ("chrome", "driver"))
    constructor, service = MagicMock(), MagicMock()
    constructor.side_effect = WebDriverException("failed start")
    monkeypatch.setattr("reddit2tiktok.browser.webdriver.Chrome", constructor)
    monkeypatch.setattr("reddit2tiktok.browser.Service", service)
    with pytest.raises(AppError, match="Chrome could not start"):
        with open_browser(config, tmp_path / "config.json"):
            pytest.fail("must not yield a broken driver")
    service.return_value.stop.assert_called_once()
    assert not list((tmp_path / "data" / "browser-profiles").iterdir())
