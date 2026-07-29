# AGENTS.md

Guidance for AI coding agents working in this repository. See `README.md` for
the user-facing project description.

## What this repo is

A single-purpose application: a battery-powered Waveshare e-paper dashboard
driven by a Raspberry Pi Zero 2 W. **The application is one file,
[`examples/minion.py`](examples/minion.py).** It fetches market quotes from a
home API, renders them to a 2.13" panel, schedules an RTC wake-up via PiSugar,
and shuts the Pi down.

The only other first-party file is
[`scripts/quickstart.sh`](scripts/quickstart.sh), the one-command installer
(`curl … | sudo bash`). It provisions deps, SPI, `/etc/minion.env`, and a
`Type=oneshot` `minion.service`.

`lib/waveshare_epd/` is a **vendored, trimmed copy** of Waveshare's driver
library. Only two modules are kept — `epd2in13_V4.py` (the panel driver) and
`epdconfig.py` (GPIO/SPI abstraction). This repo was deliberately pruned down
from the full upstream library (dozens of drivers, example scripts, demo
images). **Do not re-add upstream drivers, examples, or `pic/` assets** unless
explicitly asked; treat `lib/` as third-party code and avoid reformatting or
"cleaning it up."

## Working agreements

- **Keep the surface small.** This is a hobby device, not a framework. Prefer
  editing `minion.py` directly over introducing modules, classes, abstractions,
  or config systems. Don't add features that weren't requested.
- **Don't hardcode deployment values.** Paths, URLs, and the PiSugar endpoint
  are environment variables with defaults (`MINION_*`, see the config block at
  the top of `minion.py`). Follow that pattern for anything device-specific.
- **Match the existing style:** module-level functions, `logger` for all
  output, broad `try/except` around every external interaction (HTTP, PiSugar
  socket, display I/O) that degrades to `"N/A"` or a skipped step rather than
  crashing. The device runs unattended, so resilience beats strictness.

## Validation

There is **no test suite** and the hardware can't be exercised in CI:

- `gpiozero`, `spidev`, and `lgpio` only import on a real Raspberry Pi, and the
  display/PiSugar I/O needs the physical HAT. Importing `minion.py` off-device
  will fail at the GPIO layer.
- The realistic local check is a syntax/compile pass:
  ```bash
  python3 -m py_compile examples/minion.py
  ```
- Don't execute `minion.py` to "test" it: a real run schedules an RTC alarm and
  calls `sudo /sbin/shutdown -h now`. Reason about behavior from the code
  instead, and clean up any `__pycache__/` you create.

## Gotchas

- **The repo root must be on `PYTHONPATH`.** The import is `from
  lib.waveshare_epd import epd2in13_V4` and `lib` is not an installed package.
  CWD is *not* sufficient: `python examples/minion.py` sets `sys.path[0]` to
  `examples/`, not the working directory, so the import fails with
  `ModuleNotFoundError: No module named 'lib'`. Any launcher — cron line,
  systemd unit, shell wrapper — has to export `PYTHONPATH=<repo root>`. This has
  bitten this project once already; `scripts/quickstart.sh` now verifies it
  against the generated unit file.
- **Pillow ≥ 10.** Use `ImageDraw.textlength()` for text width;
  `textsize()` was removed in Pillow 10 and must not be reintroduced.
- **Auto-shutdown is intentionally fail-safe.** If the home API is unreachable,
  the shutdown flag can't be read and the Pi stays powered on. Preserve this —
  it's how the device is recovered when something breaks.
- **Display geometry** is landscape: the image is created as
  `(epd.height, epd.width)` = `(250, 122)`. The two-column layout and ratio
  positions are hand-tuned pixel offsets, so changing the ticker set or fonts
  means re-checking the layout, not just swapping a string.
- **The installer never rewrites `/etc/minion.env`.** Adding a new `MINION_*`
  variable therefore does *not* reach already-deployed devices — give it a
  working default in `minion.py`, and add it to the template in
  `scripts/quickstart.sh` for fresh installs.
- **The installer must never run `minion.py`** as a self-check (a run sets an
  RTC alarm and can power the machine off). Its verification is a compile +
  import check as the service user; hardware-side gaps warn, they don't fail.
- **Ticker symbols** are `SYM_*` constants. They are the home API's keys; the
  on-screen label and the key are usually the same string but need not be —
  e.g. the quote fetched under key `P` is displayed as `PSTG`.

## External contracts

`minion.py` depends on two services it does not own (full shapes in
`README.md`):

- **Home API** — [HomeAPI](https://github.com/chinmay28/HomeAPI), a key-value
  store, at `MINION_API_BASE_URL`. `minion.py` fetches the entries
  `minion-quotes`, `minion-sum`, and `minion-auto-shutdown` by key and reads
  their `value` field. HomeAPI returns JSON values as-is and wraps plain-text
  values as `{"data": "..."}`, which is why quotes is a bare object but sum and
  auto-shutdown are read from `value.data`.
- **PiSugar server** on `MINION_PISUGAR_HOST:PORT` — line protocol over TCP via
  `nc`; commands `get battery` and `rtc_alarm_set <iso8601> 127`.

If a change touches how these are called, update `README.md`'s contract section
to match.

## Git

- Develop on the branch the task specifies; create it locally if missing.
- Write focused commits with descriptive messages explaining the "why."
- Don't open pull requests unless explicitly asked.
- Do not commit build artifacts (`__pycache__/`, `*.pyc`, `*.so`) — they are
  gitignored.
