# Minion

A battery-powered e-paper dashboard. A Raspberry Pi Zero 2 W wakes on a
schedule, pulls a handful of market quotes from a home server, renders them on
a Waveshare 2.13" display, schedules its next wake-up, and powers itself back
off. Because the panel holds its image without power, the dashboard stays
readable while the Pi is asleep, so a single charge lasts a long time.

The entire application is one script: [`examples/minion.py`](examples/minion.py).
Everything under `lib/` is a trimmed copy of Waveshare's e-paper driver library
(only the parts the 2.13" V4 panel needs).

## What it shows

```
+-------------------------------------------+
| Minion                         $109,432   |   <- header: app name + BTC price
|                                           |
|  VTI: $301.20      P: $58.41              |   <- two columns of quotes
|  GLD: $214.05      ORCL: $190.77          |
| ----------------------------------------- |   <- divider
|  VTI/GLD:1.41  P/VTI:0.19  ORCL/VTI:0.63  |   <- ratios
|     05/23 07:12:03 | 42 | $98.10 | 87%    |   <- footer (black bar)
+-------------------------------------------+
```

- **Header** — the app name on the left, the Bitcoin price (formatted with
  thousands separators) on the right.
- **Columns** — `VTI` and `GLD` on the left; `P` and `ORCL` on the right.
- **Ratios** — `VTI/GLD`, `P/VTI`, `ORCL/VTI`.
- **Footer** — `timestamp | magic-sum | rotating-quote | battery%`. The third
  field rotates by time of day: `IBIT` on the morning run, `STRC` on the
  afternoon/evening run.

Any value the server omits renders as `N/A` (e.g. `P:N/A`) rather than
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
requirements.txt          Runtime Python dependencies
README.md                 This file
AGENTS.md                 Notes for AI coding agents
```

The script imports the driver with `from lib.waveshare_epd import epd2in13_V4`,
so it must be run from the repository root (the `lib` package is not installed).

## Setup

On the Pi (Raspberry Pi OS):

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

## Configuration

All deployment-specific values are environment variables with defaults baked in
for the original device. Override them to run elsewhere:

| Variable | Default | Purpose |
|----------|---------|---------|
| `MINION_LOG_FILE` | `/home/chinmay/minion.log` | Log file path |
| `MINION_FONT_PATH` | `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` | TrueType font |
| `MINION_API_BASE_URL` | `http://nakedpi.stingray-boga.ts.net:9999/api/entries` | Home API base URL |
| `MINION_PISUGAR_HOST` | `127.0.0.1` | PiSugar server host |
| `MINION_PISUGAR_PORT` | `8423` | PiSugar server port |

The quote ticker symbols are defined as `SYM_*` constants near the top of
`minion.py`. Note the renderer's two-column layout is fixed to the current set
of tickers; changing which symbols appear means editing the drawing code, not
just a config value.

## Home API contract

`minion.py` expects a small REST API at `MINION_API_BASE_URL` exposing these
entries, each returning JSON shaped as `{"value": ...}`:

- **`GET /minion-quotes`** — a map of ticker → price string, plus a
  `timestamp`:
  ```json
  {"value": {"BTC-USD": "109432", "VTI": "301.20", "GLD": "214.05",
             "P": "58.41", "ORCL": "190.77", "STRC": "98.10",
             "IBIT": "61.30", "timestamp": "05/23 07:12:03"}}
  ```
  The timestamp is `MM/DD HH:MM:SS`; the current year is assumed. An empty or
  malformed payload is treated as "server unreachable" and the display update
  is skipped.
- **`GET /minion-sum`** — the "magic sum" shown in the footer:
  ```json
  {"value": {"data": 42}}
  ```
- **`GET /minion-auto-shutdown`** — whether the Pi may power off after this run:
  ```json
  {"value": {"data": 1}}
  ```
  Truthy values: `1`, `"1"`, `"yes"`, `"YES"`.

## Running

The script is designed to run **once at boot** and then shut the Pi down,
relying on the PiSugar RTC to power it back on. Wire it into a boot service
(systemd unit or cron `@reboot`), for example:

```cron
@reboot cd /home/chinmay/minion && /usr/bin/python examples/minion.py
```

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
  `MINION_PISUGAR_HOST:PORT`, or `nc` (netcat) isn't installed.
- **Display init fails** — verify SPI is enabled and the HAT is seated; the GPIO
  Python packages must be installed on the Pi.

## Credits

The e-paper driver code under `lib/` is from Waveshare's
[e-Paper](https://github.com/waveshareteam/e-Paper) project, trimmed to the
single panel this project uses.
