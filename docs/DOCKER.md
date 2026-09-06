# Docker CLI: Linux server or Windows host

The same Linux containers work on a Linux Docker server or Docker Desktop for Windows in
**Linux-container mode**. Windows Docker Desktop normally uses its WSL 2 backend. This does not
give the container access to installed Windows speech voices: speech uses the included CPU-only
Kokoro engine with British `bm_daniel`, an alternative rather than a verified Windows Daniel match.

Install Docker/Compose separately and start its engine before following these instructions.
No host installation or Windows settings are changed by this repository. Use Docker Compose v2.34+
and a machine with several GB of free memory/disk; 8 GB RAM is a practical starting allocation for
speech plus browser work, not a measured minimum. Initial builds download substantial dependencies.
The container workflow is verified on Linux amd64; other architectures are not verified here.

## First setup

Run from the cloned repository. Explicitly set the folder containing footage you may use; it must
already exist and is mounted **read-only**. Do not point it at the repository or runtime folder.

Linux shell (run as a regular non-root user; do not set `R2T_UID=0`):

```sh
mkdir -p runtime
export VIDEOS_DIR=/srv/background-videos
export R2T_UID=$(id -u)
export R2T_GID=$(id -g)
docker compose build app
docker compose run --rm app config
```

Windows PowerShell (after cloning/opening the repository):

```powershell
New-Item -ItemType Directory -Force runtime
$env:VIDEOS_DIR = 'D:/BackgroundVideos'
docker compose build app
docker compose run --rm app config
```

The first-run wizard asks for verbosity, background folder, and voice. Enter **`/videos`** for the
folder inside the container and accept `bm_daniel` to use the local British voice. Then configure
the private browser endpoint and verify everything:

```sh
docker compose run --rm app config --browser-remote-url http://browser:4444
docker compose run --rm app doctor --browser
docker compose run --rm --no-deps app voice-test
docker compose run --rm app
```

Compose starts the browser and waits for its health check before starting the CLI. The first
`voice-test` or render downloads pinned model/voice assets into the persistent runtime folder.
The speech engine and English pronunciation model are already installed in the image.
Each new terminal session needs the environment variables above again. Alternatively put your
chosen paths and, on Linux, numeric UID/GID in a repository-local `.env` (ignored by Git).
The mount must be writable by your chosen UID/GID; do not fix permissions with `chmod 777`.

For unattended initial setup instead of the wizard:

```sh
docker compose run --rm -T app --quiet config --video-dir /videos --browser-remote-url http://browser:4444
```

Existing native configurations are not overwritten or imported automatically. The Docker config
lives at `runtime/config.json`. If migrating one deliberately, update paths to container paths
and clear `browser_binary`/`chromedriver` before selecting the remote URL. The database migration
preserves post history; old absolute export paths may need re-rendering in the new environment.

## Everyday commands

```sh
docker compose run --rm app scrape stories
docker compose run --rm -T app scrape stories --scrape-only
docker compose run --rm --no-deps app render
docker compose run --rm --no-deps app posts --details
docker compose run --rm --no-deps app config --tts-engine kokoro --voice bm_fable
docker compose run --rm --no-deps app voice-test
docker compose down
```

Use `-T` for non-interactive jobs, omit it for the menu or wizard. `--no-deps` avoids starting the
browser for commands that do not scrape. `docker compose down` stops/removes these containers and
their Compose network; the bind-mounted `runtime/` and original footage remain on disk.

Finished pairs are ordinary host files:

```text
runtime/config.json
runtime/data/posts.sqlite3
runtime/data/tts-cache/
runtime/data/artifacts/<post>-<run>/
runtime/ready4upload/<post>-<run>/with_voice.mp4
runtime/ready4upload/<post>-<run>/without_voice.mp4
```

Both exports have identical captioned video. The second has **no audio stream**, not just muted
narration or preserved background audio. Forced renders retain previous pairs. Back up `runtime/`
and monitor disk use; the application does not automatically delete old videos/history.

## Isolation and limits

- The application runs as a non-root user, with Linux capabilities dropped and no new privileges.
- The browser has no footage, data, host-profile, or Docker-socket mounts. No Grid/VNC ports are
  published. VNC/noVNC and tracing are disabled. Keep this Compose network private to this project.
- The pinned official Selenium Chromium image uses its upstream container launch defaults,
  including `--no-sandbox` inside that browser container. It relies on container isolation;
  this is not an extra Chromium sandbox boundary. No privileged container, host networking,
  host security changes, or added `SYS_ADMIN` capability is requested. Native CLI browser
  launches retain Chromium's sandbox. Do not attach sensitive mounts or expose the Grid port.
- Selenium may internally use a virtual display as required by its image; no desktop interaction
  or GUI access is needed by the user.
- Every scrape creates and quits a fresh anonymous browser session. Browser container profiles
  are ephemeral, not a login/session store. Reddit restrictions remain in effect; this test
  network requires login, and the CLI stops clearly rather than collecting a partial batch.
- Story text stays local with Kokoro. Selecting the optional Edge engine sends narration to that
  speech service. Switching between engines does not change the two-export behavior.

Rebuild periodically to receive package/base-image security updates; update the full Selenium
image tag deliberately and rerun CI. The Docker build context allowlist excludes `.env`, footage,
runtime files, virtual environments, model caches, and Git history. Images are built by CI but
are not published to a registry or deployed to your server automatically.

Sources: [Docker Desktop WSL 2](https://docs.docker.com/desktop/features/wsl/),
[Selenium Docker deployment and health checks](https://github.com/SeleniumHQ/docker-selenium),
[Upstream Chromium launch wrapper](https://github.com/SeleniumHQ/docker-selenium/blob/trunk/NodeChromium/wrap_chromium_binary),
[Remote WebDriver](https://www.selenium.dev/documentation/webdriver/drivers/remote_webdriver/).
