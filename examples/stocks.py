#!/usr/bin/python
# -*- coding:utf-8 -*-
import os
import sys
import time
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from lib.waveshare_epd import epd2in13_V4
import yfinance as yf
import logging

logging.basicConfig(level=logging.DEBUG)

refresh_interval = 300  # seconds

# Fonts
font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
font_title = ImageFont.truetype(font_path, 16)
font_main = ImageFont.truetype(font_path, 15)
font_footer = ImageFont.truetype(font_path, 11)
font_ratios = ImageFont.truetype(font_path, 10)  # Reduced font size for ratios

# Ticker order (VTI, GLD, PSTG, ORCL)
tickers = ['VTI', 'GLD', 'PSTG', 'ORCL']
ticker_objs = {t: yf.Ticker(t) for t in tickers}

# Fetch Bitcoin price
btc_ticker = yf.Ticker("BTC-USD")

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

            # Fetch the latest Bitcoin price
            btc_data = btc_ticker.history(period="1d", interval="1m")
            btc_latest = btc_data.tail(1)
            btc_price = f"{btc_latest['Close'][0]:.0f}" if not btc_latest.empty else "N/A"  # No decimals, no label

            # Calculate the ratios and truncate to 2 decimals
            try:
                vti_to_gld = round(float(quotes['VTI']) / float(quotes['GLD']), 2) if quotes['VTI'] != "N/A" and quotes['GLD'] != "N/A" else "N/A"
                pstg_to_vti = round(float(quotes['PSTG']) / float(quotes['VTI']), 2) if quotes['PSTG'] != "N/A" and quotes['VTI'] != "N/A" else "N/A"
                orcl_to_vti = round(float(quotes['ORCL']) / float(quotes['VTI']), 2) if quotes['ORCL'] != "N/A" and quotes['VTI'] != "N/A" else "N/A"
            except ValueError:
                vti_to_gld = pstg_to_vti = orcl_to_vti = "N/A"

            # Create canvas
            image = Image.new('1', (epd.height, epd.width), 255)
            draw = ImageDraw.Draw(image)

            # Header with "Minion" and Bitcoin price on the right side
            draw.rectangle((0, 0, epd.height, 22), fill=0)
            draw.text((5, 4), "Minion", font=font_title, fill=255)

            # Move Bitcoin price to the right corner with some padding
            btc_text_width, btc_text_height = draw.textsize(btc_price, font=font_title)
            right_x = epd.height - btc_text_width - 15  # 15 pixels from the right edge (added padding)
            draw.text((right_x, 4), f"${btc_price}", font=font_title, fill=255)  # Bitcoin price only

            # Two-column layout for tickers
            left_x = 10
            right_x = int(epd.height / 2) + 5
            y_start = 28
            y_spacing = 20

            # Left column: VTI, GLD
            for i, t in enumerate(tickers[:2]):  # First two tickers (VTI, GLD)
                x = left_x
                y = y_start + i * y_spacing
                draw.text((x, y), f"{t}: ${quotes[t]}", font=font_main, fill=0)

            # Right column: PSTG, ORCL
            for i, t in enumerate(tickers[2:]):  # Last two tickers (PSTG, ORCL)
                x = right_x
                y = y_start + i * y_spacing
                draw.text((x, y), f"{t}: ${quotes[t]}", font=font_main, fill=0)

            # Draw a horizontal line after 4 tickers
            line_y = y_start + 2 * y_spacing + 10  # A bit below the last ticker
            draw.line((0, line_y, epd.height, line_y), fill=0, width=1)

            # Three-column layout for ratios
            ratios_y_start = line_y + 5  # Padding below the line
            col_width = epd.height // 3  # Divide the screen into 3 columns

            # Column 1
            draw.text((10, ratios_y_start), f"VTI/GLD: {vti_to_gld}", font=font_ratios, fill=0)

            # Column 2 (Center)
            draw.text((col_width + 5, ratios_y_start), f"PSTG/VTI: {pstg_to_vti}", font=font_ratios, fill=0)

            # Column 3 (Right)
            draw.text((2 * col_width + 5, ratios_y_start), f"ORCL/VTI: {orcl_to_vti}", font=font_ratios, fill=0)

            # Footer with 12-hour timestamp, center aligned
            timestamp = datetime.now().strftime("%b %d %I:%M:%S %p")  # Month, day, 12-hour format with AM/PM
            timestamp_width, timestamp_height = draw.textsize(timestamp, font=font_footer)

            # Calculate the x-position to center the footer text
            footer_x = (epd.height - timestamp_width) // 2  # Center align the footer

            # Draw the footer
            draw.rectangle((0, epd.width - 16, epd.height, epd.width), fill=0)
            draw.text((footer_x, epd.width - 14), timestamp, font=font_footer, fill=255)

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
