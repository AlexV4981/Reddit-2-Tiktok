# Reddit → TikTok

A Linux CLI that turns Reddit stories into narrated, captioned vertical videos.
Revives [Reddit-Scraper-TTS-Python-Depracated](https://github.com/AlexV4981/Reddit-Scraper-TTS-Python-Depracated):
the menu and SQLite history remain, with a new speech and FFmpeg pipeline.

## Install on a Linux server

Requires Python 3.11+, internet access for Reddit/TTS, and FFmpeg with libass, libx264, and AAC.
On Debian/Ubuntu:

```sh
sudo apt update
sudo apt install -y python3 python3-venv ffmpeg fonts-dejavu-core git
git clone https://github.com/AlexV4981/Reddit-2-Tiktok.git
cd Reddit-2-Tiktok
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
reddit2tiktok
```

First run asks whether to show links and for the **explicit background videos folder**.
The folder must already exist. Put your own MP4, MOV, MKV, WebM, M4V, or AVI files there;
subfolders are scanned too. No background videos are downloaded.

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

1. Fetches the subreddit's **top 10 posts of the week** (`t=week`, `limit=10`).
2. Saves the title, body, link, and original metadata in SQLite, deduplicated by Reddit ID.
3. Narrates the title followed by the body with **en-GB-RyanNeural**, the selected British male voice.
4. Uses the speech service's **word boundary timestamps**, including speech pauses, for captions.
5. Randomly picks a background long enough for the measured audio and a valid starting point.
6. Center-crops the clip to **1080×1920 at 30fps**, removes background audio, and adds narration
   plus centered yellow captions with a black outline and a subtle pop, one word at a time.
7. Verifies the resulting media and atomically publishes the H.264/AAC MP4 in **ready4upload/**.

The exact top ten are saved; image/link/deleted posts without a usable story body are marked
skipped, so a batch can produce fewer than ten videos. Short backgrounds are excluded. If none
are long enough, the post fails with the required duration so you can add a longer video and retry.
Completed posts are skipped on repeat runs. A failed post does not stop the rest of the batch.
Post history is retained after rendering; repeated scrapes preserve the first saved snapshot.

Ryan was chosen for this revival. It is **not Daniel**. The old Windows `pyttsx3` setup does
not provide that voice on a Linux server. This version uses the online Microsoft Edge speech
service through `edge-tts`, so neither Windows nor a desktop session is required. The service
can change or become unavailable; failures are reported and retryable. Narration text is sent
to that service.

## Commands for SSH and unattended use

```sh
# Configure without prompts. Relative paths resolve beside the configuration file.
reddit2tiktok --verbose config --video-dir /srv/background-videos
reddit2tiktok --quiet config --voice en-GB-RyanNeural --rate=+10%
reddit2tiktok config --show
reddit2tiktok doctor

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

Without credentials the CLI tries Reddit's public JSON listing. Reddit may block anonymous
requests from server IPs. To use an approved Reddit application, supply its credentials as
environment variables (read-only app authentication; no Reddit password is required):

```sh
export REDDIT_CLIENT_ID='your-client-id'
export REDDIT_CLIENT_SECRET='your-client-secret'
reddit2tiktok scrape AmItheAsshole
```

Both variables must be set together. See `.env.example`; `.env` files are **not** loaded
automatically. Customize `reddit_user_agent` in the configuration if running as another user.
HTTP 403/401/429 errors are reported with guidance; the program does not bypass access blocks.

## Files and configuration

```text
config.json                  # first-run choices, ignored by Git
data/posts.sqlite3           # saved stories and processing state
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

## Development and verification

```sh
pip install -e '.[dev]'
ruff check .
ruff format --check .
pytest -q
```

Tests use mocked Reddit/TTS responses and synthetic media, requiring no accounts or credentials.
The integration tests invoke real FFmpeg and ffprobe to validate portrait video, audio duration,
burned-in captions, and the complete export pipeline. They skip locally if media tools are
missing. Linux CI installs the media tools and requires these tests on Python 3.11–3.13.

API references: [Reddit listings](https://www.reddit.com/dev/api/#GET_top),
[edge-tts](https://github.com/rany2/edge-tts),
[Microsoft voice catalog](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support),
[FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html).
