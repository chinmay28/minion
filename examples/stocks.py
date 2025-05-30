#!/usr/bin/python
"""
- Display stock and Bitcoin data once on the Waveshare 2.13 V4 display.
- Log all operations to /home/chinmay/stocks.log.
- Put the display to sleep.
- Calculate and set the next RTC wakeup at either 7:00 AM or 7:00 PM, whichever is next.
- Wait for 1 minute.
- Shutdown the system cleanly, with an exception of suspected manual boot.

Displays:
- Bitcoin price (header)
- VTI, GLD, PSTG, ORCL stock prices (2 columns)
- Ratios: VTI/GLD, PSTG/VTI, ORCL/VTI
- Timestamp + battery percentage (footer)
"""

import os
import time
import json
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from lib.waveshare_epd import epd2in13_V4
import yfinance as yf
import logging

# Logging
logging.basicConfig(
    filename='/home/chinmay/stocks.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Fonts
font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
font_title = ImageFont.truetype(font_path, 16)
font_main = ImageFont.truetype(font_path, 15)
font_footer = ImageFont.truetype(font_path, 11)
font_ratios = ImageFont.truetype(font_path, 10)

# Tickers
tickers = ['VTI', 'GLD', 'PSTG', 'ORCL']
btc_symbol = 'BTC-USD'
cache_file = '/home/chinmay/stock_cache.json'

# Load old cache
if os.path.exists(cache_file):
    with open(cache_file, 'r') as f:
        last_values = json.load(f)
else:
    last_values = {}

btc_ticker = yf.Ticker(btc_symbol)
ticker_objs = {t: yf.Ticker(t) for t in tickers}

MORNING_HOUR = 7
EVENING_HOUR = 19

def get_battery_percentage():
    try:
        result = os.popen('echo "get battery" | nc -q 0 127.0.0.1 8423').read().strip()
        logging.info(f"Raw battery response: {result}")
        if "battery:" in result:
            battery_value = result.split(":")[1].strip()
            return int(float(battery_value))
        else:
            return "N/A"
    except Exception as e:
        logging.error(f"Failed to get battery: {e}")
        return "N/A"

def is_am(now=None):
    if now is None:
        now = datetime.now()
    return 0 <= now.hour < 12

try:
    epd = epd2in13_V4.EPD()
    epd.init()

    logging.info("Fetching ticker data...")
    MAX_RETRIES = 5
    quotes = {}
    used_fallback = False

    for t in tickers:
        success = False
        for attempt in range(MAX_RETRIES):
            try:
                data = ticker_objs[t].history(period="1d", interval="1m")
                if not data.empty:
                    latest = data.tail(1)
                    quotes[t] = f"{latest['Close'][0]:.2f}"
                    success = True
                    break
            except Exception as e:
                logging.warning(f"Retry {attempt + 1} for ticker {t} failed: {e}")
            time.sleep(2 ** attempt)
        if not success:
            quotes[t] = last_values.get(t, "N/A")
            if quotes[t] != "N/A":
                used_fallback = True

    # Bitcoin price
    success = False
    for attempt in range(MAX_RETRIES):
        try:
            btc_data = btc_ticker.history(period="1d", interval="1m")
            if not btc_data.empty:
                btc_latest = btc_data.tail(1)
                btc_price = f"{btc_latest['Close'][0]:.0f}"
                success = True
                break
        except Exception as e:
            logging.warning(f"Retry {attempt + 1} for BTC-USD failed: {e}")
        time.sleep(2 ** attempt)
    if not success:
        btc_price = last_values.get(btc_symbol, "N/A")
        if btc_price != "N/A":
            used_fallback = True

    # Save cache only for valid values
    try:
        cache_to_save = {}
        for t in tickers:
            if quotes[t] != "N/A":
                cache_to_save[t] = quotes[t]
        if btc_price != "N/A":
            cache_to_save[btc_symbol] = btc_price
        if cache_to_save:
            with open(cache_file, 'w') as f:
                json.dump(cache_to_save, f)
    except Exception as e:
        logging.error(f"Failed to save cache: {e}")

    # Ratios
    try:
        vti_to_gld = round(float(quotes['VTI']) / float(quotes['GLD']), 2) if quotes['VTI'] != "N/A" and quotes['GLD'] != "N/A" else "N/A"
        pstg_to_vti = round(float(quotes['PSTG']) / float(quotes['VTI']), 2) if quotes['PSTG'] != "N/A" and quotes['VTI'] != "N/A" else "N/A"
        orcl_to_vti = round(float(quotes['ORCL']) / float(quotes['VTI']), 2) if quotes['ORCL'] != "N/A" and quotes['VTI'] != "N/A" else "N/A"
    except ValueError:
        vti_to_gld = pstg_to_vti = orcl_to_vti = "N/A"

    # Image drawing
    image = Image.new('1', (epd.height, epd.width), 255)
    draw = ImageDraw.Draw(image)

    # Header
    draw.rectangle((0, 0, epd.height, 22), fill=0)
    draw.text((5, 4), "Minion", font=font_title, fill=255)
    btc_text_width, _ = draw.textsize(btc_price, font=font_title)
    draw.text((epd.height - btc_text_width - 15, 4), f"${btc_price}", font=font_title, fill=255)

    # Stocks
    left_x = 10
    right_x = int(epd.height / 2) + 5
    y_start = 28
    y_spacing = 20

    for i, t in enumerate(tickers[:2]):
        draw.text((left_x, y_start + i * y_spacing), f"{t}: ${quotes[t]}", font=font_main, fill=0)

    for i, t in enumerate(tickers[2:]):
        draw.text((right_x, y_start + i * y_spacing), f"{t}: ${quotes[t]}", font=font_main, fill=0)

    # Divider
    line_y = y_start + 2 * y_spacing + 10
    draw.line((0, line_y, epd.height, line_y), fill=0, width=1)

    # Ratios
    ratios_y_start = line_y + 5
    col_width = epd.height // 3
    draw.text((10, ratios_y_start), f"VTI/GLD: {vti_to_gld}", font=font_ratios, fill=0)
    draw.text((col_width + 5, ratios_y_start), f"PSTG/VTI: {pstg_to_vti}", font=font_ratios, fill=0)
    draw.text((2 * col_width + 5, ratios_y_start), f"ORCL/VTI: {orcl_to_vti}", font=font_ratios, fill=0)

    # Footer
    timestamp = datetime.now().strftime("%b %d %I:%M:%S %p")
    battery_percent = get_battery_percentage()
    footer_text = f"{timestamp}{'*' if used_fallback else ''} | {battery_percent}%"
    footer_text_width, _ = draw.textsize(footer_text, font=font_footer)
    footer_x = (epd.height - footer_text_width) // 2

    draw.rectangle((0, epd.width - 16, epd.height, epd.width), fill=0)
    draw.text((footer_x, epd.width - 14), footer_text, font=font_footer, fill=255)

    epd.display(epd.getbuffer(image))

except Exception as e:
    logging.error(f"Failed to update display: {e}")

finally:
    logging.info("Putting display to sleep.")
    epd.sleep()

    now = datetime.now().astimezone()
    morning_waketime = now.replace(hour=MORNING_HOUR, minute=0, second=0, microsecond=0)
    evening_waketime = now.replace(hour=EVENING_HOUR, minute=0, second=0, microsecond=0)

    waketime_str = morning_waketime.isoformat()
    if is_am():
        waketime_str = evening_waketime.isoformat()

    logging.info(f"Setting RTC wakeup for {waketime_str}")
    response = os.popen(f'echo "rtc_alarm_set {waketime_str} 127" | nc -q 0 127.0.0.1 8423').read().strip()
    logging.info(f"RTC alarm response: {response}")

    if now.hour == MORNING_HOUR or now.hour == EVENING_HOUR:
        logging.info("Shutting down system.")
        os.system("sudo /sbin/shutdown -h now")
    else:
        logging.info("Possible manual boot up, not shutting down")
