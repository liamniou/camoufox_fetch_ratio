import logging
import os
import re
import requests
import time

from camoufox.sync_api import Camoufox
from prometheus_client import start_http_server, Gauge


# Site settings
USERNAME = os.getenv("USERNAME")
PASSWORD = os.getenv("PASSWORD")
MAIN_URL = os.getenv("MAIN_URL")
PROFILE_URL = os.getenv("PROFILE_URL")
DL_SELECTOR = os.getenv("DL_SELECTOR")
UL_SELECTOR = os.getenv("UL_SELECTOR")

# Exporter
EXPORTER_PORT = int(os.getenv("EXPORTER_PORT", 17500))
FETCH_INTERVAL = int(os.getenv("FETCH_INTERVAL", 3600))

# Prometheus metrics
UPLOAD_METRIC = Gauge("upload_value_bytes", "Value extracted from the webpage in bytes")
DOWNLOAD_METRIC = Gauge(
    "download_value_bytes", "Value extracted from the webpage in bytes"
)

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def convert_to_bytes(value_str):
    value_str = (
        value_str.replace("\n", "")
        .replace("\r", "")
        .replace(",", "")
        .replace(" ", "")
        .replace(" UP: ", "")
        .replace(" DL: ", "")
    )
    # Regular expression to extract numeric value and unit
    match = re.match(r"^([\d.]+)\s*(\w+)$", value_str)
    if match:
        value, unit = match.groups()
        value = float(value)
        if unit == "B":
            return value
        elif unit == "KiB" or unit == "KB":
            return value * 1024
        elif unit == "MiB" or unit == "MB":
            return value * 1024**2
        elif unit == "GiB" or unit == "GB":
            return value * 1024**3
        elif unit == "TiB" or unit == "TB":
            return value * 1024**4
    return None


def send_telegram_message(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            logging.error(f"Failed to send message to Telegram: {response.text}")
    except Exception as e:
        logging.error(f"Error sending message to Telegram: {str(e)}")


def fetch_dl_ul_data():
    with Camoufox(humanize=True, geoip=True, headless=True) as browser:
        try:
            page = browser.new_page()
            logging.info(f"Open {MAIN_URL}")
            page.goto(MAIN_URL)
            time.sleep(5)

            # Enter your credentials
            page.fill("input[name=uid]", USERNAME)
            page.fill("input[name=pwd]", PASSWORD)
            page.click("input[type=submit]")
            page.wait_for_load_state("domcontentloaded")

            logging.info(f"Fetching data from {PROFILE_URL}")
            page.goto(PROFILE_URL)
            page.wait_for_load_state("domcontentloaded")

            dl = page.text_content(DL_SELECTOR)
            ul = page.text_content(UL_SELECTOR)

            dl = convert_to_bytes(dl)
            logging.info(f"DL extracted: {dl}")

            ul = convert_to_bytes(ul)
            logging.info(f"UL extracted: {ul}")

            if dl is None or ul is None:
                send_telegram_message(f"Error extracting data for {MAIN_URL}")
                return None, None

            return dl, ul

        except Exception as e:
            print(e)
            send_telegram_message(f"Error fetching data for {MAIN_URL}")
            return None, None


if __name__ == "__main__":
    start_http_server(EXPORTER_PORT)

    while True:
        dl, ul = fetch_dl_ul_data()
        DOWNLOAD_METRIC.set(dl)
        UPLOAD_METRIC.set(ul)
        time.sleep(FETCH_INTERVAL)
