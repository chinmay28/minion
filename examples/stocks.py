#!/usr/bin/python
"""
✅ Summary of What Your Script Does:
Initializes the e-ink display (Waveshare 2.13 V4).

Every 5 minutes:

Pulls 1-minute intraday data for VTI, GLD, PSTG, and ORCL via yfinance.

Pulls Bitcoin (BTC-USD) price.

Displays:

Stock prices in two columns.

Bitcoin price in the header.

Ratios (VTI/GLD, PSTG/VTI, ORCL/VTI) in a 3-column row.

Timestamp and battery percentage in the footer.

Handles graceful shutdown with Ctrl+C.
"""
import os
import sys
import time
import json
import logging
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from lib.waveshare_epd import epd2in13_V4
import yfinance as yf

logging.basicConfig(level=logging.DEBUG)

refresh_interval = 300  # seconds

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

def get_battery_percentage():
    try:
        result = os.popen('echo "get battery" | nc -q 0 127.0.0.1 8423').read().strip()
        logging.debug(f"Raw battery response: {result}")
        # Extract the number after 'battery:' and ignore decimals
        if "battery:" in result:
            battery_value = result.split(":")[1].strip()
            battery_percent = int(float(battery_value))  # Ignore decimal part
            return battery_percent
        else:
            return "N/A"
    except Exception as e:
        logging.error(f"Failed to get battery: {e}")
        return "N/A"

try:
    epd = epd2in13_V4.EPD()
    epd.init()

    while True:
        try:
            logging.info("Fetching ticker data...")
            quotes = {}
            for t in tickers:
                data = ticker_objs[t].history(period="1d", interval="1m")
                latest = data.tail(1)
                if not latest.empty:
                    quotes[t] = f"{latest['Close'][0]:.2f}"
                else:
                    quotes[t] = "N/A"

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

            # Header with title and BTC price
            draw.rectangle((0, 0, epd.height, 22), fill=0)
            draw.text((5, 4), "Minion", font=font_title, fill=255)
            btc_text_width, _ = draw.textsize(btc_price, font=font_title)
            draw.text((epd.height - btc_text_width - 15, 4), f"${btc_price}", font=font_title, fill=255)

            # Two-column stock layout
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

            # Ratio row (3-column layout)
            ratios_y_start = line_y + 5
            col_width = epd.height // 3
            draw.text((10, ratios_y_start), f"VTI/GLD: {vti_to_gld}", font=font_ratios, fill=0)
            draw.text((col_width + 5, ratios_y_start), f"PSTG/VTI: {pstg_to_vti}", font=font_ratios, fill=0)
            draw.text((2 * col_width + 5, ratios_y_start), f"ORCL/VTI: {orcl_to_vti}", font=font_ratios, fill=0)

            # Footer: Time + Battery
            timestamp = datetime.now().strftime("%b %d %I:%M:%S %p")
            battery_percent = get_battery_percentage()
            footer_text = f"{timestamp} | {battery_percent}%"  # Removed battery icon
            footer_text_width, _ = draw.textsize(footer_text, font=font_footer)
            footer_x = (epd.height - footer_text_width) // 2

            draw.rectangle((0, epd.width - 16, epd.height, epd.width), fill=0)
            draw.text((footer_x, epd.width - 14), footer_text, font=font_footer, fill=255)

            # Display on e-ink
            epd.display(epd.getbuffer(image))

        except Exception as e:
            logging.error(f"Failed to update display: {e}")

        logging.info(f"Sleeping for {refresh_interval} seconds...")
        time.sleep(refresh_interval)

except KeyboardInterrupt:
    logging.info("Interrupted by user")
    epd.init()
    epd.Clear(0xFF)
    epd.sleep()
    sys.exit(0)
