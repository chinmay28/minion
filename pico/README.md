# Minion on a Pico W

The same dashboard as the Pi Zero build, on a Raspberry Pi Pico W with two AA
lithium cells and a TPL5110 power timer. It refreshes twice a day and the
batteries last for years.

The Pi Zero build gets its long life from the PiSugar cutting power between
wakes. This build does the same thing with a $5 timer chip: the TPL5110
applies power every two hours, the Pico does its work (usually just counting
down and powering off again in a fraction of a second; twice a day a real
refresh), pulls the DONE pin, and the TPL5110 cuts power until the next tick.
Between wakes the whole device draws about 35 nA. Two refreshes a day cost
under 1 mAh, so a pair of 3000 mAh AA lithium cells is limited by its own
shelf life, roughly a decade, not by the dashboard.

## Parts

| Part | Notes |
|---|---|
| Raspberry Pi Pico WH | Headers fit the e-paper module directly |
| Waveshare Pico-ePaper-2.13-B | 250 x 122 black/white/red, SPI, plugs onto the Pico's headers |
| Adafruit TPL5110 Low Power Timer breakout | Sets the wake interval; cuts power between wakes |
| 2 x AA lithium (Energizer L91 or similar) in a series holder | 3.0 to 3.6 V, ~3000 mAh, ~1 %/year self-discharge |
| Schottky diode, e.g. 1N5817 | In series with the timer's output; see wiring |

No charger, no UPS, no boost converter: the Pico's own regulator accepts
1.8 to 5.5 V on VSYS, so the cells feed it directly. Alkaline AAs also work,
with a shorter life and a sag in the cold. Everything fits within the Pi Zero
outline (65 x 30 mm); the cell holder sets the thickness.

## Wiring

```
AA pair +  ──►  TPL5110 VDD
AA pair -  ──►  TPL5110 GND  ──►  Pico GND (pin 38)
TPL5110 DRV  ──►|──  Pico VSYS (pin 39)      (Schottky, band toward the Pico)
TPL5110 DONE ◄──  Pico GP22 (pin 29)
```

- The Pico-ePaper-2.13-B sits on the Pico's headers; it uses GP8 to GP13 and
  3V3, nothing else. It is unpowered between wakes and keeps its image.
- The diode stops USB power on the bench flowing back into the timer's
  output. It costs about 0.3 V, which the Pico's regulator does not mind; the
  footer voltage reads after the diode.
- Set the TPL5110's interval to its maximum, two hours, with the pot or by
  soldering a resistor across the DELAY pads (see the datasheet's table). The
  firmware's `TICK_MINUTES` must match; the schedule corrects for drift, so
  roughly two hours is fine.
- DONE must be driven high by the Pico to cut power. If the Pico hangs and
  never does, the TPL5110 cycles power when the next interval expires, so a
  hang costs at most one tick. The firmware's watchdog makes that rarer.

## Firmware

MicroPython on the Pico W, plain `.py` files on the board's filesystem:

| File | Role |
|---|---|
| `main.py` | The run: countdown, Wi-Fi, fetch, paint, signal DONE |
| `config.py` | Everything device-specific: API URL, symbols, schedule, pins |
| `secrets.py` | Wi-Fi credentials; copy `secrets.example.py`, gitignored |
| `schedule.py` | Tick countdown and drift-correcting schedule (pure) |
| `localtime.py` | UTC to local time with the US DST rule (pure) |
| `homeapi.py` | Reading HomeAPI responses (pure) |
| `layout.py` | The screen as a list of drawing operations, with a validator (pure) |
| `font.py` | Scaled text on a framebuf (pure, takes framebuf-likes) |
| `epd2in13b_v4.py` | Panel driver, from Waveshare's, trimmed to landscape |
| `power.py` | Battery voltage, Wi-Fi, HTTP, NTP, DONE pin |

The modules marked pure have no hardware imports and are tested under CPython:

```bash
python3 -m unittest discover -s pico/tests -t pico
```

### How a run goes

1. Power arrives. Start the 8 s watchdog, read `wake.txt`.
2. If the countdown is above one: write it minus one, pull DONE. Done in well
   under a second.
3. Otherwise read VSYS, join Wi-Fi, sync NTP, fetch `minion-quotes` and
   `minion-sum` from the Home API, drop Wi-Fi.
4. Paint the panel: header with BTC, two quote columns, red ratio strip, a
   two-line footer with the timestamp, IBIT (morning) or STRC (evening), the
   sum and the battery voltage. Full refresh, about 15 seconds, with the core
   light-sleeping while the panel is busy.
5. Count the two-hour ticks from now to the next target in `REFRESH_AT`
   (07:15 and 19:15 local by default), write that to `wake.txt`, pull DONE.

If Wi-Fi or the API fails the panel is left alone (it still shows the last
good screen) and the countdown is set to one, so it retries on the next tick.
If the power is not cut after DONE (bench, USB, no timer wired) the run holds
for one tick and resets, so the firmware also works as a plain sleep loop.

### Schedule without a clock

The TPL5110 is a resistor timer, not a calendar, and the Pico has no RTC
across power cuts. So the device never assumes it knows the time: on each
refresh it learns it (NTP, falling back to the quotes' timestamp), counts the
ticks to the next target hour, and stores that. Each refresh re-anchors the
schedule, so timer drift stays within half a tick instead of accumulating.
See `schedule.py` and its tests for the edge cases.

### Home API

The device reads two entries by key from `API_BASE_URL`, exactly as the Pi
Zero build does (the contract is in the top-level README): the quotes object
under `value`, and the sum under `value.data`. It does not read
`minion-auto-shutdown`: there is nothing to shut down.

The URL must be reachable from the Wi-Fi network: the Pico is not on the
tailnet, so use the server's LAN name or address.

## Installing

```bash
pip install mpremote
cp pico/secrets.example.py pico/secrets.py   # fill in ssid and password
pico/install.sh                              # copies the modules, writes version.py, resets
```

The installer bakes the repo version into `version.py` using
`scripts/version.sh`, the same way `quickstart.sh` does for the Pi Zero
runner, and never overwrites a `secrets.py` already on the board.

For development, set `WATCHDOG = False` and `LIGHTSLEEP_WHILE_BUSY = False`
in `config.py`: the watchdog resets a REPL session every 8 seconds, and light
sleep drops the USB serial console. Watch a run with `mpremote run pico/main.py`
or just `mpremote` after a reset.

## Known geometry quirk

In landscape the framebuffer is 250 x 128 but the panel shows 250 x 122; the
controller pads rows to whole bytes. On the panels this was built against the
six invisible rows are at the top, which is what `VISIBLE_Y0 = 6` encodes. If
your build shows the gap at the bottom (header clipped, blank strip below the
footer), set it to 0. `layout.validate` checks every operation against the
visible area so a change there cannot silently clip text.
