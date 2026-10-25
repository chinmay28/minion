"""The hardware edges: battery voltage, Wi-Fi, HTTP, NTP, and the TPL5110.

Nothing here is unit-tested; it only runs on the Pico W. Keep it thin and
keep decisions out of it: it fetches and signals, ``main.py`` decides.
"""

import machine
import network
import utime

try:
    import requests
except ImportError:
    import urequests as requests


def read_vsys():
    """VSYS in volts, or None. On a Pico W ADC3 shares a pin with the radio;
    driving WL_CS (GP25) high first makes it read the VSYS/3 divider. Read
    this before bringing Wi-Fi up."""
    try:
        machine.Pin(25, machine.Pin.OUT, value=1)
        machine.Pin(29, machine.Pin.IN)
        raw = machine.ADC(29).read_u16()
        return raw * 3 * 3.3 / 65535
    except Exception:
        return None


def wifi_connect(ssid, password, timeout_ms, idle):
    """Join the network; return the WLAN or None after ``timeout_ms``."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    try:
        wlan.config(pm=0xA11140)   # no radio power-save: we want a fast join
    except (ValueError, OSError):
        pass
    wlan.connect(ssid, password)
    waited = 0
    while not wlan.isconnected() and waited < timeout_ms:
        idle(250)
        waited += 250
    if not wlan.isconnected():
        wifi_off(wlan)
        return None
    return wlan


def wifi_off(wlan):
    """Power the radio down. Harmless to call twice."""
    try:
        wlan.disconnect()
    except Exception:
        pass
    try:
        wlan.active(False)
    except Exception:
        pass
    try:
        wlan.deinit()
    except Exception:
        pass


def get_json(url, timeout_s):
    """Decoded JSON for a 200 response, else None. Never raises."""
    r = None
    try:
        r = requests.get(url, timeout=timeout_s)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None
    finally:
        if r is not None:
            try:
                r.close()
            except Exception:
                pass


def ntp_utc(host):
    """Sync the RTC from NTP and return the UTC time tuple. Raises on failure."""
    import ntptime
    ntptime.host = host
    ntptime.settime()
    return utime.localtime()


def done(pin_no):
    """Tell the TPL5110 we are finished. If it is wired, power is gone before
    this returns; if it is not (USB, bench), the call just returns."""
    pin = machine.Pin(pin_no, machine.Pin.OUT, value=0)
    utime.sleep_ms(10)
    pin.value(1)
    utime.sleep_ms(200)
    pin.value(0)
