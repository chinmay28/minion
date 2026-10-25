# Minion on a Pico W: everything device-specific lives here. Edit in place,
# then run install.sh to copy it to the board. Wi-Fi credentials go in
# secrets.py (see secrets.example.py), never here.

# --- Home API ---------------------------------------------------------------
# HomeAPI's entries endpoint. It must resolve on the Wi-Fi network the Pico
# joins: a LAN hostname or IP. The Pico is not on the tailnet, so a Tailscale
# name will not work here.
API_BASE_URL = "http://nakedpi:9999/api/entries"
HTTP_TIMEOUT_S = 5

QUOTES_KEY = "minion-quotes"
SUM_KEY = "minion-sum"

# Role -> key the quote is published under. The on-screen label is the role,
# so the stock published as "P" shows as PSTG.
SYMBOLS = {
    "btc": "BTC-USD",
    "vti": "VTI",
    "gld": "GLD",
    "p": "P",
    "orcl": "ORCL",
    "strc": "STRC",
    "ibit": "IBIT",
}

# --- Wi-Fi ------------------------------------------------------------------
WIFI_TIMEOUT_MS = 15000
NTP_HOST = "pool.ntp.org"

# --- Schedule ---------------------------------------------------------------
# TICK_MINUTES is the TPL5110 interval, as set by its resistor. The device
# counts ticks between refreshes; see schedule.py. REFRESH_AT are local
# minutes-of-day. FALLBACK_TICKS is used when the time could not be learned.
TICK_MINUTES = 120
REFRESH_AT = (7 * 60 + 15, 19 * 60 + 15)
FALLBACK_TICKS = 6

# Local zone as a standard-time offset from UTC, with the US daylight-saving
# rule applied when US_DST is True. Pacific: -480.
UTC_OFFSET_MINUTES = -8 * 60
US_DST = True

# --- Hardware ---------------------------------------------------------------
# GPIO wired to the TPL5110's DONE pin. GP22 is free on the Pico-ePaper-2.13-B
# (it uses GP8-13).
DONE_PIN = 22

# The landscape framebuffer is 128 rows tall but the panel shows 122. The six
# spare rows are at the top on the panels this was built against; set 0 if a
# build shows the gap at the bottom instead.
VISIBLE_Y0 = 6

# Light-sleep the core while the panel refreshes (saves ~0.1 mAh a refresh).
# It also drops the USB serial console, so turn it off while developing.
LIGHTSLEEP_WHILE_BUSY = True

# Hardware watchdog, 8 s. A hung run otherwise costs a whole tick of battery
# before the TPL5110 cycles power. Once started it cannot be stopped, which
# makes a REPL session reset every 8 s: turn it off while developing.
WATCHDOG = True

# Countdown file on the Pico's flash; see schedule.py.
STATE_FILE = "wake.txt"
