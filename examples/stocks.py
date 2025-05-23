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
from datetime import datetime, timedelta, datetime
from PIL import Image, ImageDraw, ImageFont
from lib.waveshare_epd import epd2in13_V4
import yfinance as yf

import logging

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

# Ticker symbols
tickers = ['VTI', 'GLD', 'PSTG', 'ORCL']
ticker_objs = {t: yf.Ticker(t) for t in tickers}
btc_ticker = yf.Ticker("BTC-USD")

# Wakeup schedules
MORNING_HOUR = 7
EVENING_HOUR = 19


def get_battery_percentage():
    try:
        result = os.popen('echo "get battery" | nc -q 0 127.0.0.1 8423').read().strip()
        logging.info(f"Raw battery response: {result}")
        if "battery:" in result:
            battery_value = result.split(":")[1].strip()
            battery_percent = int(float(battery_value))
            return battery_percent
        else:
            return "N/A"
    except Exception as e:
        logging.error(f"Failed to get battery: {e}")
        return "N/A"
    


def is_am(now=None):
    """Returns True if the time is between 00:00 and 11:59."""
    if now is None:
        now = datetime.now()
    return 0 <= now.hour < 12


try:
    epd = epd2in13_V4.EPD()
    epd.init()

    logging.info("Fetching ticker data...")
    quotes = {}
    for t in tickers:
        data = ticker_objs[t].history(period="1d", interval="1m")
        latest = data.tail(1)
        quotes[t] = f"{latest['Close'][0]:.2f}" if not latest.empty else "N/A"

    btc_data = btc_ticker.history(period="1d", interval="1m")
    btc_latest = btc_data.tail(1)
    btc_price = f"{btc_latest['Close'][0]:.0f}" if not btc_latest.empty else "N/A"

    # Calculate ratios
    try:
        vti_to_gld = round(float(quotes['VTI']) / float(quotes['GLD']), 2) if quotes['VTI'] != "N/A" and quotes['GLD'] != "N/A" else "N/A"
        pstg_to_vti = round(float(quotes['PSTG']) / float(quotes['VTI']), 2) if quotes['PSTG'] != "N/A" and quotes['VTI'] != "N/A" else "N/A"
        orcl_to_vti = round(float(quotes['ORCL']) / float(quotes['VTI']), 2) if quotes['ORCL'] != "N/A" and quotes['VTI'] != "N/A" else "N/A"
    except ValueError:
        vti_to_gld = pstg_to_vti = orcl_to_vti = "N/A"

    # Create canvas
    image = Image.new('1', (epd.height, epd.width), 255)
    draw = ImageDraw.Draw(image)

    # Header with BTC price
    draw.rectangle((0, 0, epd.height, 22), fill=0)
    draw.text((5, 4), "Minion", font=font_title, fill=255)
    btc_text_width, _ = draw.textsize(btc_price, font=font_title)
    draw.text((epd.height - btc_text_width - 15, 4), f"${btc_price}", font=font_title, fill=255)

    # Stock prices in two columns
    left_x = 10
    right_x = int(epd.height / 2) + 5
    y_start = 28
    y_spacing = 20

    for i, t in enumerate(tickers[:2]):
        draw.text((left_x, y_start + i * y_spacing), f"{t}: ${quotes[t]}", font=font_main, fill=0)

    for i, t in enumerate(tickers[2:]):
        draw.text((right_x, y_start + i * y_spacing), f"{t}: ${quotes[t]}", font=font_main, fill=0)

    # Divider line
    line_y = y_start + 2 * y_spacing + 10
    draw.line((0, line_y, epd.height, line_y), fill=0, width=1)

    # Ratios (3 columns)
    ratios_y_start = line_y + 5
    col_width = epd.height // 3
    draw.text((10, ratios_y_start), f"VTI/GLD: {vti_to_gld}", font=font_ratios, fill=0)
    draw.text((col_width + 5, ratios_y_start), f"PSTG/VTI: {pstg_to_vti}", font=font_ratios, fill=0)
    draw.text((2 * col_width + 5, ratios_y_start), f"ORCL/VTI: {orcl_to_vti}", font=font_ratios, fill=0)

    # Footer: Time + Battery
    timestamp = datetime.now().strftime("%b %d %I:%M %p")
    battery_percent = get_battery_percentage()
    footer_text = f"{timestamp} | {battery_percent}%"
    footer_text_width, _ = draw.textsize(footer_text, font=font_footer)
    footer_x = (epd.height - footer_text_width) // 2

    draw.rectangle((0, epd.width - 16, epd.height, epd.width), fill=0)
    draw.text((footer_x, epd.width - 14), footer_text, font=font_footer, fill=255)

    # Display the image
    epd.display(epd.getbuffer(image))

except Exception as e:
    logging.error(f"Failed to update display: {e}")

finally:
    logging.info("Putting display to sleep.")
    epd.sleep()

    # --- Set RTC wakeup time ---
    now = datetime.now().astimezone()
    # Define target times
    morning_waketime = now.replace(hour=MORNING_HOUR, minute=0, second=0, microsecond=0)
    evening_waketime = now.replace(hour=EVENING_HOUR, minute=0, second=0, microsecond=0)

    # Decide next wake time
    waketime_str = morning_waketime.isoformat()
    if is_am():
        waketime_str = evening_waketime.isoformat()


    logging.info(f"Setting RTC wakeup for {waketime_str}")
    response = os.popen(f'echo "rtc_alarm_set {waketime_str} 127" | nc -q 0 127.0.0.1 8423').read().strip()
    logging.info(f"RTC alarm response: {response}")

    if now.hour == MORNING_HOUR or now.hour == EVENING_HOUR:
        # --- Shutdown Countdown ---
        logging.info("Waiting 1 minute before shutdown...")
        time.sleep(60)

        logging.info("Shutting down system.")
        os.system("sudo /sbin/shutdown -h now")
    else:
        logging.info("Possible manual boot up, not shutting down")
