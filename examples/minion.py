#!/usr/bin/python

import os
import time
import json
import logging
import signal
import subprocess
import requests
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from lib.waveshare_epd import epd2in13_V4

# --- Logging setup ---
LOG_FILE = "/home/chinmay/minion.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger()

# --- Fonts ---
font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
font_title = ImageFont.truetype(font_path, 16)
font_main = ImageFont.truetype(font_path, 15)
font_footer = ImageFont.truetype(font_path, 11)
font_ratios = ImageFont.truetype(font_path, 10)

# --- Constants ---
MORNING_HOUR = 7
MID_DAY_HOUR = 12
EVENING_HOUR = 19
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


def get_battery_percentage():
    try:
        result = os.popen('echo "get battery" | nc -q 0 127.0.0.1 8423').read().strip()
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
    data = fetch_json("http://pi4:8000/api/minion-sum")
    try:
        result = data["value"]["sum"]
        logger.debug(f"Magic sum: {result}")
        return result
    except Exception as e:
        logger.warning(f"Malformed minion-sum response: {data}")
        return "N/A"


def get_quotes():
    data = fetch_json("http://pi4:8000/api/minion-quotes")

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
    data = fetch_json("http://pi4:8000/api/minion-auto-shutdown")
    try:
        logger.debug(f"Auto shutdown flag: {data['value']}")
        return data["value"]["enabled"] == 1
    except Exception as e:
        logger.warning(f"Malformed auto-shutdown response: {data} or exc: {e}")
        return False


def get_wake_hour(ts):
    if ts.hour < 9:
        return MID_DAY_HOUR
    if ts.hour < 14:
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

        BTC  = safe_get(quotes, "BTC-USD")
        VTI  = safe_get(quotes, "VTI")
        GLD  = safe_get(quotes, "GLD")
        PSTG = safe_get(quotes, "PSTG")
        ORCL = safe_get(quotes, "ORCL")
        STRC = safe_get(quotes, "STRC")

        # Compute ratios
        def safe_ratio(a, b):
            try:
                return round(float(a) / float(b), 2)
            except Exception as e:
                logger.warning(f"Ratio failed {a}/{b}: {e}")
                return "N/A"

        vti_to_gld = safe_ratio(VTI, GLD)
        pstg_to_vti = safe_ratio(PSTG, VTI)
        orcl_to_vti = safe_ratio(ORCL, VTI)

        magic_sum = get_magic_sum()
        battery = get_battery_percentage()

        logger.info("Start rendering...")
        image = Image.new("1", (epd.height, epd.width), 255)
        draw = ImageDraw.Draw(image)

        # Header
        draw.rectangle((0, 0, epd.height, 22), fill=0)
        draw.text((5, 4), "Minion", font=font_title, fill=255)

        try:
            btc_text = f"${int(float(BTC)):,}" if BTC != "N/A" else "BTC:N/A"
        except Exception as e:
            logger.warning(f"Failed to format BTC '{BTC}': {e}")
            btc_text = "BTC:N/A"
        w, _ = draw.textsize(btc_text, font=font_title)
        draw.text((epd.height - w - 5, 4), btc_text, font=font_title, fill=255)

        # Stock columns
        left_x, right_x = 10, epd.height // 2 + 5
        y0, dy = 28, 20
        draw.text((left_x,  y0), f"VTI: ${VTI}", font=font_main, fill=0)
        draw.text((left_x,  y0+dy), f"GLD: ${GLD}", font=font_main, fill=0)
        draw.text((right_x, y0), f"PSTG: ${PSTG}", font=font_main, fill=0)
        draw.text((right_x, y0+dy), f"ORCL: ${ORCL}", font=font_main, fill=0)

        # Divider
        line_y = y0 + 2*dy + 10
        draw.line((0, line_y, epd.height, line_y), fill=0)

        # Ratios
        ratio_y = line_y + 5
        cw = epd.height // 3
        draw.text((10,           ratio_y), f"VTI/GLD:{vti_to_gld}", font=font_ratios, fill=0)
        draw.text((cw + 5,       ratio_y), f"PSTG/VTI:{pstg_to_vti}", font=font_ratios, fill=0)
        draw.text((2*cw + 5,     ratio_y), f"ORCL/VTI:{orcl_to_vti}", font=font_ratios, fill=0)

        # Footer
        strc_disp = f"${STRC}" if STRC != "N/A" else "STRC:N/A"
        footer_text = f"{timestamp} | {magic_sum} | {strc_disp} | {battery}%"
        fw, _ = draw.textsize(footer_text, font=font_footer)
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
    ts = parse_custom_timestamp(timestamp)
    wake_hour = get_wake_hour(ts)
    waketime_str = ts.replace(hour=wake_hour, minute=15, second=0, microsecond=0).isoformat()

    logger.info(f"Setting RTC wakeup: {waketime_str}")
    rtc_rsp = os.popen(f'echo "rtc_alarm_set {waketime_str} 127" | nc -q 0 127.0.0.1 8423').read().strip()
    logger.info(f"RTC response: {rtc_rsp}")

    shutdown()


if __name__ == "__main__":
    main()
