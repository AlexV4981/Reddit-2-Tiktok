# Reddit → TikTok

A Linux CLI that turns Reddit stories into narrated, captioned vertical videos.
Revives [Reddit-Scraper-TTS-Python-Depracated](https://github.com/AlexV4981/Reddit-Scraper-TTS-Python-Depracated):
the menu and SQLite history remain, with **headless Selenium scraping**, speech, and FFmpeg rendering.
No desktop session or Reddit API credentials are required.

## Install on a Linux server

Requires Python 3.11+, Chrome/Chromium, internet access for Reddit/TTS, and FFmpeg with libass,
libx264, and AAC. A headless browser needs its normal Linux libraries even without a GUI.
For example, on Debian 12+ (the Chromium packages also install those libraries):

```sh
sudo apt update
sudo apt install -y python3 python3-venv ffmpeg fonts-dejavu-core git chromium chromium-driver
git clone https://github.com/AlexV4981/Reddit-2-Tiktok.git
cd Reddit-2-Tiktok
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
reddit2tiktok config
reddit2tiktok config --browser-binary /usr/bin/chromium --chromedriver /usr/bin/chromedriver
reddit2tiktok doctor --browser
reddit2tiktok
```

First run asks whether to show links and for the **explicit background videos folder**.
The folder must already exist. Put your own MP4, MOV, MKV, WebM, M4V, or AVI files there;
subfolders are scanned too. No background videos are downloaded.

On Ubuntu or another distribution, install the same Python/media prerequisites and a supported
Chrome/Chromium build using that distribution's instructions. Set `browser_binary` to it;
Selenium Manager can obtain its matching driver. If both executable settings are empty, Manager
downloads a dedicated Chrome for Testing and matching driver into `data/browser-cache/` on
first use. This requires internet access and sufficient disk space. On platforms without a
managed Chrome build, such as Linux ARM64, provide a matching system Chromium/driver pair.
Run the program as a **regular user with Chrome's sandbox available**, not as root.

```text
Reddit → TikTok
1) Scrape + create videos
2) Config
3) Show all scraped posts
4) Retry unfinished videos
0) Exit
```

Choose **1**, enter a subreddit such as `AmItheAsshole`, and wait for the videos.
Normal mode displays each post's title; verbose mode adds its Reddit link.
Progress, errors, and output filenames are displayed in both modes.

## What a scrape does

1. Launches isolated headless Chrome with Selenium and opens the subreddit's **top posts of the
   week** (`t=week`, `limit=10`), collecting up to ten ranked, non-promoted, non-pinned posts.
   Pagination keeps the weekly filter; repeated cards do not count twice.
2. Opens each selected post to read its **full body**, rather than using a truncated feed preview,
   then closes the browser. Comments and nested crosspost cards are not scraped as stories.
3. Saves the title, body, link, and original metadata in SQLite, deduplicated by Reddit ID.
4. Narrates the title followed by the body with **en-GB-RyanNeural**, the selected British male voice.
5. Uses the speech service's **word boundary timestamps**, including speech pauses, for captions.
6. Randomly picks a background long enough for the measured audio and a valid starting point.
7. Center-crops the clip to **1080×1920 at 30fps**, removes background audio, and adds narration
   plus centered yellow captions with a black outline and a subtle pop, one word at a time.
8. Verifies the resulting media and atomically publishes the H.264/AAC MP4 in **ready4upload/**.

The selected top posts are saved; image/link/deleted posts without a usable story body are marked
skipped, so a batch can produce fewer than ten videos. Short backgrounds are excluded. If none
are long enough, the post fails with the required duration so you can add a longer video and retry.
Completed posts are skipped on repeat runs. A failed post does not stop the rest of the batch.
Post history is retained after rendering; repeated scrapes preserve the first saved snapshot.

Ryan was chosen for this revival. It is **not Daniel**. The old Windows `pyttsx3` setup does
not provide that voice on a Linux server. This version uses the online Microsoft Edge speech
service through `edge-tts`, so neither Windows nor a desktop session is required. The service
can change or become unavailable; failures are reported and retryable. Narration text is sent
to that service.
See [Daniel and Docker voice options](docs/VOICE_OPTIONS.md) for the exact-voice route and
Linux-compatible alternatives. Docker packaging is a separate follow-up; this revision does
not add a container or change the accepted Ryan default.

## Commands for SSH and unattended use

```sh
# Configure without prompts. Relative paths resolve beside the configuration file.
reddit2tiktok --verbose config --video-dir /srv/background-videos
reddit2tiktok --quiet config --voice en-GB-RyanNeural --rate=+10%
reddit2tiktok config --show
reddit2tiktok doctor
reddit2tiktok doctor --browser

# Scrape and render this week's top ten
reddit2tiktok scrape AmItheAsshole

# Scrape now, render later
reddit2tiktok scrape AmItheAsshole --scrape-only
reddit2tiktok render

# Inspect history; --details explicitly adds IDs/status/errors
reddit2tiktok posts
reddit2tiktok --verbose posts
reddit2tiktok posts --details
reddit2tiktok posts --json

# Retry one post or create a new version (old video is preserved)
reddit2tiktok render POST_ID
reddit2tiktok render POST_ID --force

# List currently available voices
reddit2tiktok voices --locale en-GB

# Fixed config location when run by a scheduler
/srv/Reddit-2-Tiktok/.venv/bin/reddit2tiktok \
  --config /srv/Reddit-2-Tiktok/config.json scrape AmItheAsshole
```

Global flags (`--config`, `--verbose`, `--quiet`) go **before** the command. Verbosity flags
are temporary overrides except with `config`, which saves them. `posts --json` deliberately
exports complete records, including links and bodies, regardless of display verbosity.
`render` retries unfinished work and missing exports; `render --force` regenerates every saved
post, including completed ones, into new filenames. Exit codes: `0` success, `1` error or a
batch with failures, `2` invalid command arguments, `130` interrupted input/render.

## Reddit access

Scraping uses **Selenium and rendered HTML**, not requests, Reddit JSON endpoints, or OAuth.
The default is `old.reddit.com`; a parser for the modern `www.reddit.com` post-card layout is
also included. Select the interface explicitly:

```sh
reddit2tiktok config --reddit-frontend old
# Optional alternative layout:
reddit2tiktok config --reddit-frontend www
```

Chrome uses a fresh temporary profile per scrape; it does not open your personal browser,
reuse its cookies, or require a GUI. `browser_timeout` controls page/DOM waits (30 seconds by
default), and `scrape_delay` spaces post/page navigation (1 second by default). The scraper
checks at most five listing batches; small communities can return fewer than ten posts.

Reddit may still block anonymous browsers or server IPs. Network blocks, verification, private
communities, and unexpected layouts fail with guidance; **Selenium does not bypass access
controls**. There is no proxy rotation, CAPTCHA solver, stealth driver, or login automation.
If a selected post cannot be loaded, the new scrape is not partially saved. Existing history
and finished videos are retained. Live Reddit access is separate from the offline test suite
and is not guaranteed by passing tests. Respect Reddit's rules and the rights of story authors.

## Files and configuration

```text
config.json                  # first-run choices, ignored by Git
data/posts.sqlite3           # saved stories and processing state
data/browser-cache/         # managed browser/driver downloads, when needed
data/browser-profiles/      # temporary scrape profiles (removed when the browser closes)
data/artifacts/<id>-<run>/   # narration.mp3, captions.ass, manifest.json
ready4upload/<id>-<run>.mp4   # verified finished videos
```

The manifest records the narration, word timestamps, voice, source link, background, and
random offset. Audio/captions/manifests are retained for troubleshooting, including failed
runs. Monitor disk usage on a server; there is no automatic history or artifact deletion.
Interrupted renders can be retried with `render`. An OS file lock prevents simultaneous renders
against the same data folder and is released on exit or crash.

See `config.example.json` for all settings. Copy it to `config.json` if configuring by hand.
Paths resolve relative to the config file, so cron/SSH working directories do not change the
data/output location when you supply `--config`. Keep data and output outside the input videos
folder. Dimensions must be even and 9:16; `720×1280` can reduce CPU cost. `caption_y` sets the
vertical position (0.62 by default); `font_size`, `font`, `rate`, `crf`, and `preset` are adjustable.
Use footage and stories you have permission to publish. Uploading to TikTok is a manual step.

### Upgrading from v0.1

Run `pip install -e .` again to install Selenium and Beautiful Soup. Existing `config.json` and
SQLite post history remain usable; no database reset is needed. The old `reddit_user_agent`
setting is accepted and ignored, then removed on the next configuration save. The obsolete
`.env.example` has been removed; `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` are no longer used.
Your own `.env` file is not modified. Previously saved posts keep their original bodies and status.

The scraping modules are separated by responsibility: `browser.py` manages browser startup
and cleanup, `reddit_html.py` handles HTML selectors, `reddit.py` controls navigation, and
`models.py` defines the shared post record. SQLite, speech, captions, and rendering do not
depend on Selenium driver objects.

## Development and verification

```sh
pip install -e '.[dev]'
ruff check .
ruff format --check .
pytest -q
```

Unit tests cover both HTML layouts, weekly pagination, full bodies, deduplication, access errors,
browser cleanup, config migration, storage, speech boundaries, and recovery. Browser tests launch
**real Selenium Chrome against a local HTTP fixture server**, including JavaScript-delayed posts.
An end-to-end test runs Selenium → SQLite → deterministic test audio → real FFmpeg → verified MP4,
checking audio replacement and actual burned-in caption frames. TTS is stubbed so tests do not
send stories to an external service. No accounts or Reddit credentials are needed.

Media tests skip locally if FFmpeg is absent. Browser tests are opt-in locally:

```sh
R2T_REQUIRE_FFMPEG=1 R2T_REQUIRE_BROWSER=1 \
R2T_CHROME_BINARY=/usr/bin/chromium R2T_CHROMEDRIVER=/usr/bin/chromedriver pytest -q
```

Omit both browser paths to test managed downloads, or supply only the browser path to let Manager
obtain the driver. Linux CI requires real browser and media tests on Python 3.11–3.13; missing
tools fail rather than silently skip. No test attempts to bypass a Reddit restriction.

References: [Selenium Manager](https://www.selenium.dev/documentation/selenium_manager/),
[edge-tts](https://github.com/rany2/edge-tts),
[Microsoft voice catalog](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support),
[FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html).
