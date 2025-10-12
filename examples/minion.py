import os
import sys
import time
import json
import logging
import signal
import requests
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from concurrent.futures import ThreadPoolExecutor, as_completed
from lib.waveshare_epd import epd2in13_V4
import yfinance as yf

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
EVENING_HOUR = 19
API_BASE = "http://pi4:3006/api/address"
REQUEST_TIMEOUT = 300
MAX_RETRIES = 5
INITIAL_BACKOFF = 5
MAX_WORKERS = 10
CACHE_FILE = "/home/chinmay/minion_cache.json"
PRIVATE_DATA_DIR = "/home/chinmay/minion/examples/private_data"
HOME_LAT_LONG = (37.18, -121.89)
WEATHER_BASE_URL = "https://api.openweathermap.org/data/3.0/onecall"

# --- Load Weather API Key ---
try:
    with open("/home/chinmay/weather_api.txt", "r") as f:
        WEATHER_API_KEY = f.read().strip()
except Exception as e:
    logger.error(f"Failed to read weather API key: {e}")
    WEATHER_API_KEY = ""

terminate = False


def handle_sigint(signum, frame):
    """Gracefully handle Ctrl+C"""
    global terminate
    logger.warning("Interrupted by user. Exiting gracefully...")
    terminate = True


signal.signal(signal.SIGINT, handle_sigint)


# --- Utility Functions ---
def get_battery_percentage():
    try:
        result = os.popen('echo "get battery" | nc -q 0 127.0.0.1 8423').read().strip()
        if "battery:" in result:
            battery_value = result.split(":")[1].strip()
            return int(float(battery_value))
        return "N/A"
    except Exception as e:
        logger.error(f"Failed to get battery: {e}")
        return "N/A"


def is_am(now=None):
    now = now or datetime.now()
    return 0 <= now.hour < 12


def fetch_funded_sum(address):
    url = f"{API_BASE}/{address}"
    retries = 0
    backoff = INITIAL_BACKOFF

    while retries <= MAX_RETRIES and not terminate:
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 504:
                logger.warning(f"{address}: 504 Gateway Timeout. Retrying in 120 seconds...")
                time.sleep(120)
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["chain_stats"]["funded_txo_sum"]
        except Exception as e:
            logger.error(f"{address}: {e}")
            if retries == MAX_RETRIES:
                return 0
            retries += 1
            time.sleep(backoff)
            backoff *= 2
    return 0


def calculate_grand_total():
    input_files = [
        os.path.join(PRIVATE_DATA_DIR, f)
        for f in os.listdir(PRIVATE_DATA_DIR)
        if os.path.isfile(os.path.join(PRIVATE_DATA_DIR, f))
        and f.lower().endswith(".txt")
    ]
    grand_total = 0
    for filename in input_files:
        if terminate:
            break
        with open(filename, "r") as f:
            addresses = [line.strip() for line in f if line.strip()]
        subtotal = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(fetch_funded_sum, addr): addr for addr in addresses}
            for future in as_completed(futures):
                if terminate:
                    break
                try:
                    subtotal += future.result()
                except Exception as e:
                    logger.error(f"Error processing address: {e}")
        grand_total += subtotal
    return grand_total


# --- Main Display Logic ---
def main():
    epd = epd2in13_V4.EPD()
    epd.init()
    btc_ticker = yf.Ticker("BTC-USD")
    tickers = ["VTI", "GLD", "PSTG", "ORCL"]
    ticker_objs = {t: yf.Ticker(t) for t in tickers}

    # Load cache
    last_values = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            last_values = json.load(f)

    quotes = {}
    used_fallback = False

    for t in tickers:
        try:
            data = ticker_objs[t].history(period="1d", interval="1m")
            quotes[t] = f"{data['Close'].iloc[-1]:.2f}" if not data.empty else last_values.get(t, "N/A")
        except:
            quotes[t] = last_values.get(t, "N/A")
            used_fallback = True

    try:
        btc_data = btc_ticker.history(period="1d", interval="1m")
        btc_price = f"{btc_data['Close'].iloc[-1]:.0f}" if not btc_data.empty else last_values.get("BTC-USD", "N/A")
    except:
        btc_price = last_values.get("BTC-USD", "N/A")
        used_fallback = True

    # Save cache
    cache_to_save = {t: quotes[t] for t in tickers if quotes[t] != "N/A"}
    if btc_price != "N/A":
        cache_to_save["BTC-USD"] = btc_price
    with open(CACHE_FILE, "w") as f:
        json.dump(cache_to_save, f)

    # Ratios
    try:
        vti_to_gld = round(float(quotes["VTI"]) / float(quotes["GLD"]), 2)
        pstg_to_vti = round(float(quotes["PSTG"]) / float(quotes["VTI"]), 2)
        orcl_to_vti = round(float(quotes["ORCL"]) / float(quotes["VTI"]), 2)
    except:
        vti_to_gld = pstg_to_vti = orcl_to_vti = "N/A"

    # Grand total sats
    grand_total_sats = calculate_grand_total()

    # --- Draw image ---
    image = Image.new("1", (epd.height, epd.width), 255)
    draw = ImageDraw.Draw(image)

    # Header
    draw.rectangle((0, 0, epd.height, 22), fill=0)
    draw.text((5, 4), "Minion", font=font_title, fill=255)
    btc_text = f"${btc_price}"
    btc_text_width, _ = draw.textsize(btc_text, font=font_title)
    draw.text((epd.height - btc_text_width - 5, 4), btc_text, font=font_title, fill=255)

    # Stock data
    left_x, right_x = 10, int(epd.height / 2) + 5
    y_start, y_spacing = 28, 20
    for i, t in enumerate(tickers[:2]):
        draw.text((left_x, y_start + i * y_spacing), f"{t}: ${quotes[t]}", font=font_main, fill=0)
    for i, t in enumerate(tickers[2:]):
        draw.text((right_x, y_start + i * y_spacing), f"{t}: ${quotes[t]}", font=font_main, fill=0)

    # Divider line
    line_y = y_start + 2 * y_spacing + 10
    draw.line((0, line_y, epd.height, line_y), fill=0)

    # Ratios
    ratios_y = line_y + 5
    col_width = epd.height // 3
    draw.text((10, ratios_y), f"VTI/GLD: {vti_to_gld}", font=font_ratios, fill=0)
    draw.text((col_width + 5, ratios_y), f"PSTG/VTI: {pstg_to_vti}", font=font_ratios, fill=0)
    draw.text((2 * col_width + 5, ratios_y), f"ORCL/VTI: {orcl_to_vti}", font=font_ratios, fill=0)

    # Footer
    timestamp = datetime.now().strftime("%m/%d %H:%M")
    battery_percent = get_battery_percentage()

    try:
        weather_data = requests.get(
            f"{WEATHER_BASE_URL}?lat={HOME_LAT_LONG[0]}&lon={HOME_LAT_LONG[1]}&units=imperial&exclude=current,minutely,hourly,alerts&appid={WEATHER_API_KEY}",
            timeout=10,
        )
        data = weather_data.json()
        min_temp, max_temp = round(data["daily"][0]["temp"]["min"]), round(data["daily"][0]["temp"]["max"])
        weather_str = f"{min_temp}-{max_temp}"
    except Exception as e:
        logger.error(f"Weather fetch failed: {e}")
        weather_str = "N/A"

    footer_text = f"{timestamp}{'*' if used_fallback else ''} | {grand_total_sats} | {weather_str} | {battery_percent}%"
    footer_text_width, _ = draw.textsize(footer_text, font=font_footer)
    footer_x = (epd.height - footer_text_width) // 2

    draw.rectangle((0, epd.width - 16, epd.height, epd.width), fill=0)
    draw.text((footer_x, epd.width - 14), footer_text, font=font_footer, fill=255)

    epd.display(epd.getbuffer(image))
    epd.sleep()

    now = datetime.now().astimezone()
    wake_hour = EVENING_HOUR if is_am(now) else MORNING_HOUR
    waketime_str = now.replace(hour=wake_hour, minute=0, second=0, microsecond=0).isoformat()
    os.popen(f'echo "rtc_alarm_set {waketime_str} 127" | nc -q 0 127.0.0.1 8423').read()

    if now.hour in [MORNING_HOUR, EVENING_HOUR]:
        os.system("sudo /sbin/shutdown -h now")
    else:
        logger.info("Manual boot suspected; skipping shutdown.")


if __name__ == "__main__":
    main()
