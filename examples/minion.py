#!/usr/bin/python

import os
import time
import logging
import signal
import requests
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from lib.waveshare_epd import epd2in13_V4

# --- Configuration (override via environment) ---
LOG_FILE = os.environ.get("MINION_LOG_FILE", "/home/chinmay/minion.log")
FONT_PATH = os.environ.get("MINION_FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
API_BASE_URL = os.environ.get("MINION_API_BASE_URL", "http://nakedpi.stingray-boga.ts.net:9999/api/entries")
PISUGAR_HOST = os.environ.get("MINION_PISUGAR_HOST", "127.0.0.1")
PISUGAR_PORT = os.environ.get("MINION_PISUGAR_PORT", "8423")

# --- Logging setup ---
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger()

# --- Fonts ---
font_title = ImageFont.truetype(FONT_PATH, 16)
font_main = ImageFont.truetype(FONT_PATH, 15)
font_footer = ImageFont.truetype(FONT_PATH, 11)
font_ratios = ImageFont.truetype(FONT_PATH, 10)

# --- Constants ---
MORNING_HOUR = 7
EVENING_HOUR = 19

# Quote keys as published by the Home API
SYM_BTC = "BTC-USD"
SYM_VTI = "VTI"
SYM_GLD = "GLD"
SYM_P = "P"
SYM_ORCL = "ORCL"
SYM_STRC = "STRC"
SYM_IBIT = "IBIT"

terminate = False


# --- Signal Handling ---
def handle_sigint(signum, frame):
    global terminate
    logger.warning("Interrupted by user. Exiting gracefully...")
    terminate = True

signal.signal(signal.SIGINT, handle_sigint)


# --- Utility Functions ---
def safe_get(d, key, default="N/A"):
    """Safe dict getter with logging."""
    if not isinstance(d, dict):
        logger.error(f"safe_get() received non-dict: {d}")
        return default
    value = d.get(key, default)
    if value == "N/A":
        logger.warning(f"Missing key: {key}")
    return value


def fmt_price(label, value, as_int=False):
    """Format a quote as a dollar value, or 'LABEL:N/A' when missing/invalid."""
    if value == "N/A":
        return f"{label}:N/A"
    try:
        if as_int:
            return f"${int(float(value)):,}"
        return f"${value}"
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to format {label} '{value}': {e}")
        return f"{label}:N/A"


def get_battery_percentage():
    try:
        result = os.popen(f'echo "get battery" | nc -q 0 {PISUGAR_HOST} {PISUGAR_PORT}').read().strip()
        logger.debug(f"Battery raw response: {result}")
        if "battery:" in result:
            val = result.split(":")[1].strip()
            pct = int(float(val))
            logger.debug(f"Battery parsed: {pct}%")
            return pct
        logger.warning("Battery response format invalid")
        return "N/A"
    except Exception as e:
        logger.exception("Failed to read battery:")
        return "N/A"


def api_url(entry_key):
    return f"{API_BASE_URL}/{entry_key}"


# --- Robust JSON fetch with retries ---
def fetch_json(url, retries=10, delay=3):
    for attempt in range(1, retries + 1):
        try:
            logger.debug(f"Requesting {url} (attempt {attempt})")
            response = requests.get(url, timeout=2)
            response.raise_for_status()
            logger.debug(f"Raw JSON from {url}: {response.text}")
            return response.json()
        except Exception as e:
            logger.warning(f"Attempt {attempt} failed for {url}: {e}")
            time.sleep(delay)

    logger.error(f"All {retries} attempts FAILED for url {url}")
    return {}  # Always return safe empty dict


def get_magic_sum():
    data = fetch_json(api_url("minion-sum"))
    try:
        result = data["value"]["data"]
        logger.debug(f"Magic sum: {result}")
        return result
    except Exception as e:
        logger.warning(f"Malformed minion-sum response: {data}")
        return "N/A"


def get_quotes():
    data = fetch_json(api_url("minion-quotes"))

    if "value" not in data:
        logger.error(f"Quotes missing 'value' field: {data}")
        return {}

    quotes = data["value"]

    if not isinstance(quotes, dict):
        logger.error(f"'value' returned non-dict quotes: type={type(quotes)} data={quotes}")
        return {}

    logger.debug(f"Final parsed quotes: {quotes}")
    return quotes


def should_auto_shutdown():
    data = fetch_json(api_url("minion-auto-shutdown"))
    try:
        logger.debug(f"Auto shutdown flag: {data['value']}")
        return data["value"]["data"] in (1, "1", "yes", "YES")
    except Exception as e:
        logger.warning(f"Malformed auto-shutdown response: {data} or exc: {e}")
        return False


def get_wake_hour(ts):
    if ts.hour < 12:
        return EVENING_HOUR
    return MORNING_HOUR


def shutdown():
    if should_auto_shutdown():
        logger.info("Auto-shutdown enabled. Shutting down.")
        os.system("sudo /sbin/shutdown -h now")
    else:
        logger.info("Auto-shutdown disabled — NOT shutting down.")


def parse_custom_timestamp(ts_str):
    try:
        # Assume current year if year not present
        this_year = datetime.now().year
        full_str = f"{this_year} {ts_str}"
        return datetime.strptime(full_str, "%Y %m/%d %H:%M:%S").astimezone()
    except Exception as e:
        logger.warning(f"Failed to parse custom timestamp '{ts_str}': {e}")
        return datetime.now()


# --- Main Program ---
def main():
    logger.info("---------------------------------------------")
    logger.info("------------------MiNiON---------------------")
    logger.info("---------------------------------------------")

    logger.info("Making REST calls to Home API...")
    quotes = get_quotes()
    timestamp = quotes.pop("timestamp", datetime.now().strftime("%m/%d %H:%M:%S"))

    ts = parse_custom_timestamp(timestamp)
    wake_hour = get_wake_hour(ts)

    if not quotes:
        logger.warning("Home API server not reachable. Skipping display update")
    else:
        logger.info("Initializing display...")
        try:
            epd = epd2in13_V4.EPD()
            epd.init()
        except Exception as e:
            logger.exception("Display initialization FAILED:")
            return

        BTC  = safe_get(quotes, SYM_BTC)
        VTI  = safe_get(quotes, SYM_VTI)
        GLD  = safe_get(quotes, SYM_GLD)
        P    = safe_get(quotes, SYM_P)
        ORCL = safe_get(quotes, SYM_ORCL)
        STRC = safe_get(quotes, SYM_STRC)
        IBIT = safe_get(quotes, SYM_IBIT)

        # Compute ratios
        def safe_ratio(a, b):
            try:
                return round(float(a) / float(b), 2)
            except Exception as e:
                logger.warning(f"Ratio failed {a}/{b}: {e}")
                return "N/A"

        vti_to_gld = safe_ratio(VTI, GLD)
        p_to_vti = safe_ratio(P, VTI)
        orcl_to_vti = safe_ratio(ORCL, VTI)

        magic_sum = get_magic_sum()
        battery = get_battery_percentage()

        logger.info("Start rendering...")
        image = Image.new("1", (epd.height, epd.width), 255)
        draw = ImageDraw.Draw(image)

        # Header
        draw.rectangle((0, 0, epd.height, 22), fill=0)
        draw.text((5, 4), "Minion", font=font_title, fill=255)

        btc_text = fmt_price("BTC", BTC, as_int=True)
        w = int(draw.textlength(btc_text, font=font_title))
        draw.text((epd.height - w - 5, 4), btc_text, font=font_title, fill=255)

        # Stock columns
        left_x, right_x = 10, epd.height // 2 + 5
        y0, dy = 28, 20
        draw.text((left_x,  y0), f"VTI: ${VTI}", font=font_main, fill=0)
        draw.text((left_x,  y0+dy), f"GLD: ${GLD}", font=font_main, fill=0)
        draw.text((right_x, y0), f"P: ${P}", font=font_main, fill=0)
        draw.text((right_x, y0+dy), f"ORCL: ${ORCL}", font=font_main, fill=0)

        # Divider
        line_y = y0 + 2*dy + 10
        draw.line((0, line_y, epd.height, line_y), fill=0)

        # Ratios
        ratio_y = line_y + 5
        cw = epd.height // 3
        draw.text((10,       ratio_y), f"VTI/GLD:{vti_to_gld}", font=font_ratios, fill=0)
        draw.text((cw + 5,   ratio_y), f"P/VTI:{p_to_vti}", font=font_ratios, fill=0)
        draw.text((2*cw + 5, ratio_y), f"ORCL/VTI:{orcl_to_vti}", font=font_ratios, fill=0)

        # Footer
        ibit_disp = fmt_price("IBIT", IBIT)
        strc_disp = fmt_price("STRC", STRC)
        if wake_hour < 15:
            footer_text = f"{timestamp} | {magic_sum} | {strc_disp} | {battery}%"
        else:
            footer_text = f"{timestamp} | {magic_sum} | {ibit_disp} | {battery}%"

        fw = int(draw.textlength(footer_text, font=font_footer))
        fx = (epd.height - fw) // 2

        draw.rectangle((0, epd.width - 16, epd.height, epd.width), fill=0)
        draw.text((fx, epd.width - 14), footer_text, font=font_footer, fill=255)

        logger.info(f"Footer rendered: {footer_text}")

        # Display
        try:
            epd.display(epd.getbuffer(image))
            epd.sleep()
            logger.info("Display update complete.")
        except Exception:
            logger.exception("Display update FAILED")

    # --- RTC Wake ---
    waketime_str = ts.replace(hour=wake_hour, minute=15, second=0, microsecond=0).isoformat()

    logger.info(f"Setting RTC wakeup: {waketime_str}")
    rtc_rsp = os.popen(f'echo "rtc_alarm_set {waketime_str} 127" | nc -q 0 {PISUGAR_HOST} {PISUGAR_PORT}').read().strip()
    logger.info(f"RTC response: {rtc_rsp}")

    shutdown()


if __name__ == "__main__":
    main()
