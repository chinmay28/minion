"""Minion on a Raspberry Pi Pico W, powered through a TPL5110.

Every time the TPL5110 applies power this runs from the top. Most wakes only
decrement the countdown in flash and signal DONE, which cuts the power again
within a fraction of a second. When the countdown runs out: read the battery,
join Wi-Fi, learn the time, fetch the quotes and the sum, drop Wi-Fi, paint
the panel, work out how many ticks until the next target hour, store that,
and signal DONE.

The panel keeps its image unpowered, so a failed run leaves the last good
screen up and simply tries again on the next tick. If DONE does not cut the
power (USB on the bench, or no TPL5110), the run holds for one tick and
resets, so the same code works as a plain sleep loop.
"""

import machine
import utime

import config
import homeapi
import layout
import localtime
import power
import schedule
from epd2in13b_v4 import EPD

try:
    import secrets
except ImportError:
    secrets = None

try:
    from version import VERSION
except ImportError:
    VERSION = "v0.0.0"

_wdt = None


def log(*parts):
    print("[minion]", *parts)


def feed():
    if _wdt is not None:
        _wdt.feed()


def idle_awake(ms):
    """Wait with the core running; safe while Wi-Fi is up."""
    while ms > 0:
        step = ms if ms < 100 else 100
        utime.sleep_ms(step)
        feed()
        ms -= step


def idle_sleepy(ms):
    """Wait with the core light-sleeping; only once Wi-Fi is down."""
    while ms > 0:
        step = ms if ms < 100 else 100
        if config.LIGHTSLEEP_WHILE_BUSY:
            machine.lightsleep(step)
        else:
            utime.sleep_ms(step)
        feed()
        ms -= step


def read_state():
    try:
        with open(config.STATE_FILE) as f:
            return f.read()
    except OSError:
        return None


def write_state(text):
    try:
        with open(config.STATE_FILE, "w") as f:
            f.write(text)
    except OSError as e:
        log("could not write", config.STATE_FILE, e)


def local_minutes(quotes):
    """Minutes past local midnight from NTP, else from the quotes' timestamp,
    else None. Wi-Fi must be up for the first; the second is a little stale."""
    try:
        utc = power.ntp_utc(config.NTP_HOST)
        local = localtime.to_local(utc, config.UTC_OFFSET_MINUTES, config.US_DST)
        log("time via ntp:", local)
        return localtime.minute_of_day(local)
    except Exception as e:
        log("ntp failed:", e)
    minutes = schedule.parse_quote_timestamp(quotes.get("timestamp"))
    log("time via quotes timestamp:", minutes)
    return minutes


def paint(view):
    ops = layout.compose(view, config.VISIBLE_Y0)
    layout.validate(ops, config.VISIBLE_Y0)
    epd = EPD(idle=idle_sleepy)
    epd.black.fill(layout.PAPER)
    epd.red.fill(layout.PAPER)
    layout.render(ops, epd.black, epd.red, epd.scratch)
    epd.display()
    epd.sleep()


def refresh():
    """One full refresh. Returns the number of ticks until the next one."""
    volts = power.read_vsys()
    log("vsys:", volts)

    if secrets is None:
        log("no secrets.py; cannot join Wi-Fi")
        return config.FALLBACK_TICKS

    wlan = power.wifi_connect(secrets.ssid, secrets.password, config.WIFI_TIMEOUT_MS, idle_awake)
    if wlan is None:
        log("Wi-Fi join failed; keeping the last image, retrying next tick")
        return 1
    log("Wi-Fi up:", wlan.ifconfig()[0])

    try:
        quotes = homeapi.parse_quotes(
            power.get_json(homeapi.url_for(config.API_BASE_URL, config.QUOTES_KEY), config.HTTP_TIMEOUT_S))
        feed()
        sum_text = homeapi.parse_text_value(
            power.get_json(homeapi.url_for(config.API_BASE_URL, config.SUM_KEY), config.HTTP_TIMEOUT_S))
        feed()
        now = local_minutes(quotes)
        feed()
    finally:
        power.wifi_off(wlan)

    if not quotes:
        log("no quotes; keeping the last image, retrying next tick")
        return 1

    view = layout.view_from(quotes, sum_text, volts, now, config.SYMBOLS)
    log("view:", view)
    paint(view)
    log("panel updated")

    if now is None:
        return config.FALLBACK_TICKS
    return schedule.ticks_until_next(now, config.REFRESH_AT, config.TICK_MINUTES)


def main():
    global _wdt
    log(VERSION)
    if config.WATCHDOG:
        _wdt = machine.WDT(timeout=8000)

    due, remaining = schedule.next_state(read_state())
    if not due:
        write_state(str(remaining))
        log("not due; %d ticks to go" % remaining)
    else:
        try:
            ticks = refresh()
        except Exception as e:
            log("refresh failed:", e)
            ticks = 1
        write_state(str(ticks))
        log("next refresh in %d ticks" % ticks)

    power.done(config.DONE_PIN)

    # Still here: nobody cut the power. Hold for one tick and start over.
    log("power not cut; holding one tick")
    idle_sleepy(config.TICK_MINUTES * 60 * 1000)
    machine.reset()


main()
