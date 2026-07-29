# Minion

A battery-powered e-paper dashboard. A Raspberry Pi Zero 2 W wakes on a
schedule, pulls a handful of market quotes from a home server
([HomeAPI](https://github.com/chinmay28/HomeAPI)), renders them on a Waveshare
2.13" display, schedules its next wake-up, and powers itself back
off. Because the panel holds its image without power, the dashboard stays
readable while the Pi is asleep, so a single charge lasts a long time.

The entire application is one script: [`examples/minion.py`](examples/minion.py).
Everything under `lib/` is a trimmed copy of Waveshare's e-paper driver library
(only the parts the 2.13" V4 panel needs).

## Quick start

On a Raspberry Pi with the HAT seated:

```bash
curl -fsSL https://raw.githubusercontent.com/chinmay28/minion/master/scripts/quickstart.sh | sudo bash
```

That installs the dependencies, enables SPI, writes `/etc/minion.env`, and
installs `minion.service` — a `Type=oneshot` unit that runs one refresh at every
boot. Point it at your own server on the first install:

```bash
curl -fsSL https://raw.githubusercontent.com/chinmay28/minion/master/scripts/quickstart.sh \
  | sudo MINION_API_BASE_URL=http://your-host:9999/api/entries bash
```

**Nothing is run at install time.** Minion paints the panel on the *next* boot,
and the PiSugar RTC is what powers the Pi back on. That is deliberate: a run
schedules an RTC alarm and — if the server's auto-shutdown flag is set — powers
the machine off, so an installer that "verified itself" by running the app would
shut down the Pi you are typing on. To do it anyway, pass `MINION_RUN_NOW=1`.

The code is cloned to `/opt/minion/src` and the installer keeps it there: re-run
the same command any time and it fetches the latest `MINION_REF` into that
checkout. It is idempotent, it never overwrites `/etc/minion.env`, and a commit
that fails its compile/import check is rolled back. See
[Installer options](#installer-options) for the full list of variables, or
[Setup](#setup) to do it by hand.

## What it shows

```
+-------------------------------------------+
| Minion                         $109,432   |   <- header: app name + BTC price
|                                           |
|  VTI: $301.20      PSTG: $58.41           |   <- two columns of quotes
|  GLD: $214.05      ORCL: $190.77          |
| ----------------------------------------- |   <- divider
|  VTI/GLD:1.41 PSTG/VTI:0.19 ORCL/VTI:0.63 |   <- ratios
|     05/23 07:12:03 | 42 | $98.10 | 87%    |   <- footer (black bar)
+-------------------------------------------+
```

- **Header** — the app name on the left, the Bitcoin price (formatted with
  thousands separators) on the right.
- **Columns** — `VTI` and `GLD` on the left; `PSTG` and `ORCL` on the right.
- **Ratios** — `VTI/GLD`, `PSTG/VTI`, `ORCL/VTI`.
- **Footer** — `timestamp | magic-sum | rotating-quote | battery%`. The third
  field rotates by time of day: `IBIT` on the morning run, `STRC` on the
  afternoon/evening run.

Any value the server omits renders as `N/A` (e.g. `IBIT:N/A`) rather than
crashing.

## Hardware

| Part | Notes |
|------|-------|
| Raspberry Pi Zero 2 W | The compute. Runs headless. |
| Waveshare 2.13" e-Paper HAT (V4) | 250 × 122 px, black & white. Driver: `epd2in13_V4`. |
| PiSugar 2 | LiPo UPS with a built-in RTC. Provides battery readings and the scheduled wake-up alarm. |
| Case | A Pwnagotchi case — these are built for a Pi Zero + 2.13" Waveshare HAT, so the panel and ports line up. |

### GPIO wiring (BCM numbering)

The Waveshare HAT seats directly on the 40-pin header. For reference, the
driver expects:

| Signal | BCM pin |
|--------|---------|
| RST  | 17 |
| DC   | 25 |
| CS   | 8 (SPI0 CE0) |
| BUSY | 24 |
| PWR  | 18 |
| MOSI | 10 |
| SCLK | 11 |

## How it works

A single run of `minion.py` does the following:

1. **Fetch data** from the home API (`minion-quotes`, `minion-sum`,
   `minion-auto-shutdown`), with retries. The quotes payload also carries the
   authoritative `timestamp` — the Pi does not rely on its own clock.
2. **Render** the dashboard to the panel. If the API is unreachable, this step
   is skipped (the panel keeps its last image) but the run still continues to
   the wake/shutdown step.
3. **Read the battery** percentage from PiSugar over its local TCP socket.
4. **Schedule the next wake-up.** Morning runs schedule the next alarm for
   ~19:15; afternoon/evening runs schedule it for ~07:15. The result is two
   refreshes a day.
5. **Shut down** — but only if the server's auto-shutdown flag is set. If the
   API is down (so the flag can't be read), the Pi deliberately stays on, which
   makes the device easy to recover and debug.

The PiSugar RTC then powers the Pi back on at the scheduled time and the cycle
repeats.

## Repository layout

```
examples/minion.py        The application (the only first-party code)
lib/waveshare_epd/        Trimmed Waveshare driver library
  epd2in13_V4.py            Panel driver for the 2.13" V4
  epdconfig.py              GPIO/SPI abstraction (Raspberry Pi path)
scripts/quickstart.sh     One-command installer (deps, SPI, config, boot unit)
requirements.txt          Runtime Python dependencies
README.md                 This file
AGENTS.md                 Notes for AI coding agents
```

The script imports the driver with `from lib.waveshare_epd import epd2in13_V4`,
and `lib` is not an installed package — so **the repository root must be on
`PYTHONPATH`**. Changing directory to it is *not* enough: `python
examples/minion.py` puts `examples/` on `sys.path[0]`, not the working
directory, so without `PYTHONPATH` the import fails with `ModuleNotFoundError:
No module named 'lib'`. Run it the way the boot hook does:

```bash
cd ~/minion && export PYTHONPATH=$(pwd) && python examples/minion.py
```

## Setup

What [`scripts/quickstart.sh`](scripts/quickstart.sh) automates, step by step —
follow this if you would rather do it by hand. On the Pi (Raspberry Pi OS):

1. **Enable SPI** — `sudo raspi-config` → *Interface Options* → *SPI* → enable,
   then reboot.
2. **Install the fonts** used by the renderer:
   ```bash
   sudo apt install fonts-dejavu-core
   ```
3. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
   `Pillow` (drawing), `requests` (HTTP), and `spidev` / `gpiozero` / `lgpio`
   (display I/O on the Pi). The GPIO packages only install on a Pi.
4. **Install PiSugar's server** (`pisugar-server`) per its own docs, so the
   battery query and RTC alarm commands on `127.0.0.1:8423` work.
5. **Allow passwordless shutdown** for the user that runs the script (the
   script calls `sudo /sbin/shutdown -h now`), e.g. via a `sudoers` rule.

`pisugar-server` is the one piece the installer will not install for you — it is
a third-party service with its own installer. Quickstart detects whether it is
answering and warns if it is not.

## Installer options

`scripts/quickstart.sh` reads these from the environment; all are optional.

| Variable | Default | Purpose |
|----------|---------|---------|
| `MINION_REPO` | `https://github.com/chinmay28/minion.git` | Source to clone |
| `MINION_REF` | `master` | Branch, tag, or commit to deploy |
| `MINION_USER` | the invoking `sudo` user, else `minion` | User the service runs as |
| `MINION_SRC_DIR` | unset | Deploy a checkout *you* maintain instead of the managed clone |
| `MINION_PREFIX` | `/opt/minion` | Install prefix (source → `$PREFIX/src`, venv → `$PREFIX/venv`) |
| `MINION_CONFIG` | `/etc/minion.env` | Env file the unit reads |
| `MINION_API_BASE_URL` | the original device's tailnet URL | Seeded into the config on **first install only** |
| `MINION_LOG_FILE` | `<service user's home>/minion.log` | Seeded into the config on first install only |
| `ENABLE_SPI` | `auto` | `never` to leave the SPI interface alone |
| `MINION_PISUGAR_WAIT` | `30` | Seconds to wait at boot for PiSugar (`0` disables); seeded into the config |
| `MINION_RUN_NOW` | `0` | `1` to run one refresh after installing — **may power the machine off** |

Notes on how it behaves:

- **The deployed code lives at `/opt/minion/src`, and the installer owns it.**
  Every run fetches `MINION_REF` into that clone, so the running commit is always
  known and "re-run to upgrade" genuinely upgrades. A checkout in a home
  directory is whatever state it was left in, which is why it isn't used by
  default — set `MINION_SRC_DIR` to deploy one deliberately. Such a tree is
  yours: only fast-forwarded, never when dirty, never reset, never chowned.
- **A leftover `@reboot` crontab entry is detected and reported.** If you set
  this device up by hand, that line still fires at boot alongside the unit — and
  from its *own* checkout, so the two would be running different commits. The
  installer tells you and prints the command; removing it is your call.
- **A now-unused `~/minion` checkout is called out** so it doesn't sit there
  looking authoritative while nothing runs it.
- **The unit waits for PiSugar before running.** systemd starts it much earlier
  in boot than cron ever did, early enough to lose a race with the PiSugar
  server. `After=` alone doesn't fix that — it's a no-op against a unit whose
  name doesn't match, and for a `Type=simple` service it only means the process
  forked, not that it's listening. So the installer also writes
  `/opt/minion/bin/wait-for-pisugar` and runs it as `ExecStartPre`: it polls the
  PiSugar port for up to `MINION_PISUGAR_WAIT` seconds, releases the moment it
  answers, and always exits 0 so a missing PiSugar degrades instead of blocking
  boot.
- **The config file is written once and never rewritten.** It is the only state
  Minion has, and it is what makes one device differ from another; clobbering it
  on upgrade would silently repoint your Pi at somebody else's API.
- **The service user defaults to whoever ran `sudo`**, matching the original
  deployment (log in that user's home, already in the `spi`/`gpio` groups). Piped
  into a bare root shell it falls back to a dedicated `minion` system account.
- **Off a Raspberry Pi it still installs**, skipping the SPI and PiSugar steps
  and warning about them, so it is usable for staging on a plain Debian box.
- **Hardware-side gaps warn rather than fail.** A missing panel, PiSugar, or
  unreachable API are all conditions Minion is designed to survive at runtime, so
  they should not abort an install.

## Configuration

All deployment-specific values are environment variables with defaults baked in
for the original device. Override them to run elsewhere — quickstart writes them
into `/etc/minion.env`, which `minion.service` loads as an `EnvironmentFile`:

| Variable | Default | Purpose |
|----------|---------|---------|
| `MINION_LOG_FILE` | `/home/chinmay/minion.log` | Log file path |
| `MINION_FONT_PATH` | `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` | TrueType font |
| `MINION_API_BASE_URL` | `http://nakedpi.stingray-boga.ts.net:9999/api/entries` | Home API base URL |
| `MINION_PISUGAR_HOST` | `127.0.0.1` | PiSugar server host |
| `MINION_PISUGAR_PORT` | `8423` | PiSugar server port |
| `MINION_PISUGAR_WAIT` | `30` | Seconds the boot service waits for PiSugar to start listening (`0` disables). Read by the unit's readiness gate, not by `minion.py`. |

The quote ticker symbols are defined as `SYM_*` constants near the top of
`minion.py`. Note the renderer's two-column layout is fixed to the current set
of tickers; changing which symbols appear means editing the drawing code, not
just a config value. The display label can also differ from the lookup key —
for example, the stock fetched under the key `P` is shown as `PSTG`.

## Home API contract

The data is served by [HomeAPI](https://github.com/chinmay28/HomeAPI), a
self-hosted key-value store. Each datum is an *entry* with a `key` and a
`value`; `minion.py` fetches three entries **by key** from
`MINION_API_BASE_URL` (which already includes the `/api/entries` path):

```
GET {MINION_API_BASE_URL}/{key}
```

HomeAPI resolves numeric path segments as IDs and everything else as keys, so
`.../api/entries/minion-quotes` returns the entry whose key is `minion-quotes`.
A single-entry response is the full record (`id`, `category`, `key`, `value`,
`created_at`, `updated_at`), but `minion.py` only reads `value`.

The shape of `value` follows a HomeAPI convention: a stored value that is
itself valid JSON is returned as-is, while a plain-text value is wrapped as
`{"data": "..."}`. That is why the quotes entry below is a bare object while
the other two are nested under `data`.

- **`minion-quotes`** — stored as a JSON object: ticker → price string, plus a
  `timestamp`. The full response:
  ```json
  {
    "id": 1,
    "category": "minion",
    "key": "minion-quotes",
    "value": {
      "BTC-USD": "109432", "VTI": "301.20", "GLD": "214.05", "P": "58.41",
      "ORCL": "190.77", "STRC": "98.10", "IBIT": "61.30",
      "timestamp": "05/23 07:12:03"
    },
    "created_at": "...",
    "updated_at": "..."
  }
  ```
  The timestamp is `MM/DD HH:MM:SS`; the current year is assumed. An empty or
  malformed payload is treated as "server unreachable" and the display update
  is skipped.
- **`minion-sum`** — plain text; the "magic sum" shown in the footer, read from
  `value.data`:
  ```json
  {"value": {"data": "42"}}
  ```
- **`minion-auto-shutdown`** — plain text; whether the Pi may power off after
  this run, read from `value.data`:
  ```json
  {"value": {"data": "1"}}
  ```
  Truthy values: `1`, `"1"`, `"yes"`, `"YES"`.

## Running

The script is designed to run **once at boot** and then shut the Pi down,
relying on the PiSugar RTC to power it back on. Quickstart wires that up as a
`Type=oneshot` systemd unit with no `Restart=` — a failed run must not retry in a
loop, because the panel keeps its last image and retrying would only burn
battery:

```bash
systemctl status minion          # result of the last boot's run
systemctl start minion           # force a refresh now (may power the Pi off)
journalctl -u minion -n 50
systemctl disable minion         # stop running it at boot
```

By hand, any boot hook works — a unit of your own or cron `@reboot`. Note the
`PYTHONPATH` export; without it the driver import fails (see
[Repository layout](#repository-layout)):

```cron
@reboot cd ~/minion/ && export PYTHONPATH=$(pwd) && python examples/minion.py
```

If you switch to the systemd unit, **remove the crontab line.** Otherwise both
fire at boot, racing for the same GPIO pins — and from different checkouts, since
quickstart deploys `/opt/minion/src` while that line runs `~/minion`.

> **Heads up:** running `minion.py` will (by default) schedule an RTC alarm and
> attempt to shut the machine down. Don't run it casually on a Pi you want to
> stay on — clear the server's auto-shutdown flag first, or run it somewhere
> without PiSugar/`sudo shutdown`.

## Logging

Everything is logged at `DEBUG` level to `MINION_LOG_FILE`
(`/home/chinmay/minion.log` by default), including raw API responses, the
battery reading, the chosen wake time, and the RTC server's reply. Start here
when debugging a run.

## Troubleshooting

- **Blank/stale display** — the API was likely unreachable, so the update was
  skipped. Check connectivity to `MINION_API_BASE_URL` and the log.
- **Pi won't power off** — auto-shutdown is gated on the server flag; if the
  API is down the Pi stays on by design. Confirm `minion-auto-shutdown` returns
  a truthy `value.data`.
- **Battery shows `N/A`** — the PiSugar server isn't reachable on
  `MINION_PISUGAR_HOST:PORT`, or `nc` (netcat) isn't installed. Note the RTC
  alarm goes through the *same* socket, so an `N/A` battery usually means the
  wake-up alarm was not set either — check `RTC response:` in the log, and treat
  that as the real problem. If this started after switching from an `@reboot`
  crontab to `minion.service`, it is a boot race: the unit starts far earlier
  than cron did. Re-run `quickstart.sh` to install the readiness gate, or raise
  `MINION_PISUGAR_WAIT`. `journalctl -u minion -b` shows the gate giving up.
- **Display init fails** — verify SPI is enabled and the HAT is seated; the GPIO
  Python packages must be installed on the Pi.

## Credits

The e-paper driver code under `lib/` is from Waveshare's
[e-Paper](https://github.com/waveshareteam/e-Paper) project, trimmed to the
single panel this project uses.
