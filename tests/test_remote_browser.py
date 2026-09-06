from dataclasses import replace
from unittest.mock import MagicMock

import pytest
from selenium.common.exceptions import WebDriverException
from urllib3.exceptions import MaxRetryError

from reddit2tiktok.browser import open_browser
from reddit2tiktok.cli import main
from reddit2tiktok.config import load_config
from reddit2tiktok.errors import AppError


@pytest.mark.parametrize("failure", [False, True])
def test_remote_browser_has_fresh_profile_and_always_quits(config, tmp_path, monkeypatch, failure):
    constructor = MagicMock()
    monkeypatch.setattr("reddit2tiktok.browser.webdriver.Remote", constructor)
    monkeypatch.setattr(
        "reddit2tiktok.browser.browser_paths", lambda *a: pytest.fail("local download")
    )
    configured = replace(config, browser_remote_url="http://browser:4444")
    try:
        with open_browser(configured, tmp_path / "config.json") as driver:
            assert driver is constructor.return_value
            kwargs = constructor.call_args.kwargs
            assert kwargs["command_executor"] == configured.browser_remote_url
            assert kwargs["client_config"].timeout == 60
            args = kwargs["options"].arguments
            assert "--headless=new" in args
            assert not any(a.startswith("--user-data-dir") for a in args)
            if failure:
                raise ValueError("test failure")
    except ValueError:
        assert failure
    constructor.return_value.quit.assert_called_once()
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("error", [WebDriverException("offline"), MaxRetryError(None, "test")])
def test_remote_connection_failure_is_actionable(config, tmp_path, monkeypatch, error):
    constructor = MagicMock(side_effect=error)
    monkeypatch.setattr("reddit2tiktok.browser.webdriver.Remote", constructor)
    with pytest.raises(AppError, match="Remote Selenium failed"):
        with open_browser(
            replace(config, browser_remote_url="http://browser:4444"), tmp_path / "c"
        ):
            pytest.fail("unreachable")


def test_remote_timeout_setup_failure_closes_created_session(config, tmp_path, monkeypatch):
    constructor = MagicMock()
    constructor.return_value.set_page_load_timeout.side_effect = WebDriverException("failed")
    monkeypatch.setattr("reddit2tiktok.browser.webdriver.Remote", constructor)
    with pytest.raises(AppError):
        with open_browser(
            replace(config, browser_remote_url="http://browser:4444"), tmp_path / "c"
        ):
            pytest.fail("unreachable")
    constructor.return_value.quit.assert_called_once()


@pytest.mark.parametrize(
    "url",
    [
        [],
        "file:///etc/test",
        "http://u:p@browser",
        "http://browser:bad",
        "http://browser?q=x",
        "http://browser/#x",
        "http://browser\n",
    ],
)
def test_invalid_remote_urls_are_rejected(config, url):
    with pytest.raises(AppError):
        replace(config, browser_remote_url=url).validate()


def test_remote_configuration_and_local_conflict(config, tmp_path):
    path = tmp_path / "config.json"
    assert (
        main(
            [
                "--config",
                str(path),
                "config",
                "--video-dir",
                config.video_dir,
                "--browser-remote-url",
                "http://browser:4444",
            ]
        )
        == 0
    )
    assert load_config(path).browser_remote_url == "http://browser:4444"
    with pytest.raises(AppError, match="cannot be combined"):
        replace(
            config, browser_remote_url="http://browser:4444", browser_binary="chrome"
        ).validate()
