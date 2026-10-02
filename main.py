import asyncio
import json
import logging
import os
import re
import requests

from camoufox.async_api import AsyncCamoufox
from prometheus_client import start_http_server, Gauge

# ── Configuration ────────────────────────────────────────────────────
# SITES_CONFIG is a JSON array of site objects, each with:
#   name, username, password, main_url, profile_url, dl_selector, ul_selector
#
# For backward-compat, fall back to the legacy single-site env vars.

SITES_CONFIG_RAW = os.getenv("SITES_CONFIG")
if SITES_CONFIG_RAW:
    SITES = json.loads(SITES_CONFIG_RAW)
else:
    SITES = [
        {
            "name": os.getenv("MAIN_URL", "default"),
            "username": os.getenv("USERNAME"),
            "password": os.getenv("PASSWORD"),
            "main_url": os.getenv("MAIN_URL"),
            "profile_url": os.getenv("PROFILE_URL"),
            "dl_selector": os.getenv("DL_SELECTOR"),
            "ul_selector": os.getenv("UL_SELECTOR"),
        }
    ]

EXPORTER_PORT = int(os.getenv("EXPORTER_PORT", 17500))
FETCH_INTERVAL = int(os.getenv("FETCH_INTERVAL", 3600))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", 3))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", 60))

# Notifications
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# ── Prometheus metrics (labelled by site) ────────────────────────────
UPLOAD_METRIC = Gauge(
    "upload_value_bytes",
    "Upload value extracted from the webpage in bytes",
    ["site"],
)
DOWNLOAD_METRIC = Gauge(
    "download_value_bytes",
    "Download value extracted from the webpage in bytes",
    ["site"],
)

UNIT_MULTIPLIERS = {
    "B": 1,
    "KB": 1024,
    "KIB": 1024,
    "MB": 1024**2,
    "MIB": 1024**2,
    "GB": 1024**3,
    "GIB": 1024**3,
    "TB": 1024**4,
    "TIB": 1024**4,
}


def convert_to_bytes(value_str):
    cleaned = (
        value_str.replace("\n", "")
        .replace("\r", "")
        .replace(",", "")
        .replace("\xa0", "")  # non-breaking space
        .replace(" UP: ", "")
        .replace(" DL: ", "")
        .strip()
    )
    match = re.match(r"^([\d.]+)\s*(\w+)$", cleaned)
    if not match:
        return None
    value, unit = match.groups()
    multiplier = UNIT_MULTIPLIERS.get(unit.upper())
    if multiplier is None:
        return None
    return float(value) * multiplier


def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        response = requests.post(url, json=payload, timeout=15)
        if response.status_code != 200:
            logging.error(f"Failed to send Telegram message: {response.text}")
    except Exception as e:
        logging.error(f"Error sending Telegram message: {e}")


def send_discord_message(message):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        payload = {"content": message}
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if response.status_code not in (200, 204):
            logging.error(f"Failed to send Discord message: {response.text}")
    except Exception as e:
        logging.error(f"Error sending Discord message: {e}")


def send_notification(message):
    """Send a notification to all configured channels."""
    send_telegram_message(message)
    send_discord_message(message)


# ── Browser management ───────────────────────────────────────────────
_browser_ctx = None   # AsyncCamoufox context-manager
_browser = None       # browser instance


async def get_browser():
    """Return a long-lived browser instance, creating one if needed."""
    global _browser_ctx, _browser
    if _browser is not None:
        try:
            # Quick health check — list contexts to verify connection
            _browser.contexts
            return _browser
        except Exception:
            logging.warning("Browser connection lost, restarting…")
            await close_browser()

    logging.info("Launching Camoufox browser…")
    _browser_ctx = AsyncCamoufox(humanize=True, geoip=True, headless=True)
    _browser = await _browser_ctx.__aenter__()
    return _browser


async def close_browser():
    global _browser_ctx, _browser
    if _browser_ctx is not None:
        try:
            await _browser_ctx.__aexit__(None, None, None)
        except Exception:
            pass
    _browser_ctx = None
    _browser = None


# Track login state per site so we only log in when needed.
_logged_in = {}  # site main_url -> page


async def _ensure_logged_in(browser, site):
    """Return a page that is logged in for the given site.

    Re-uses existing pages/sessions when possible.  Only logs in again
    when the page is missing or the session has expired.
    """
    site_key = site["main_url"]
    page = _logged_in.get(site_key)

    # Check if existing page is still usable
    if page is not None:
        try:
            await page.goto(site["profile_url"], timeout=30000)
            await page.wait_for_load_state("domcontentloaded")
            # Verify we're still logged in by checking for the DL selector
            if await page.query_selector(site["dl_selector"]):
                logging.info(f"[{site_key}] Reusing existing session")
                return page
            logging.info(f"[{site_key}] Session expired, re-logging in…")
        except Exception:
            logging.info(f"[{site_key}] Page stale, creating new one…")
            try:
                await page.close()
            except Exception:
                pass

    # Create new page and log in
    page = await browser.new_page()
    logging.info(f"[{site_key}] Navigating to {site['main_url']}")
    await page.goto(site["main_url"], timeout=30000)
    await page.wait_for_load_state("domcontentloaded")

    logging.info(f"[{site_key}] Logging in as {site['username']}")
    await page.fill("input[name=uid]", site["username"])
    await page.fill("input[name=pwd]", site["password"])
    await page.click("input[type=submit]")
    await page.wait_for_load_state("domcontentloaded")

    logging.info(f"[{site_key}] Navigating to profile {site['profile_url']}")
    await page.goto(site["profile_url"], timeout=30000)
    await page.wait_for_load_state("domcontentloaded")

    _logged_in[site_key] = page
    return page


async def fetch_site_data(site):
    """Fetch DL/UL data for a single site, with retries."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            browser = await get_browser()
            page = await _ensure_logged_in(browser, site)

            # Wait for the selector to be present (up to 15 s)
            await page.wait_for_selector(site["dl_selector"], timeout=15000)

            dl_raw = await page.text_content(site["dl_selector"])
            ul_raw = await page.text_content(site["ul_selector"])

            dl = convert_to_bytes(dl_raw)
            ul = convert_to_bytes(ul_raw)

            logging.info(f"[{site['main_url']}] DL={dl}, UL={ul}")

            if dl is None or ul is None:
                raise ValueError(
                    f"Could not parse values — DL raw='{dl_raw}', UL raw='{ul_raw}'"
                )

            return dl, ul

        except Exception as e:
            logging.error(
                f"[{site['main_url']}] Attempt {attempt}/{MAX_RETRIES} failed: {e}"
            )
            # Invalidate session so next attempt starts fresh
            _logged_in.pop(site["main_url"], None)

            if attempt < MAX_RETRIES:
                # On second failure, restart the whole browser
                if attempt >= 2:
                    logging.warning("Restarting browser after repeated failures…")
                    await close_browser()
                await asyncio.sleep(RETRY_DELAY)
            else:
                send_notification(
                    f"❌ Failed to fetch data for {site['main_url']} "
                    f"after {MAX_RETRIES} attempts: {e}"
                )
                return None, None


# ── Main loop ────────────────────────────────────────────────────────
async def main():
    start_http_server(EXPORTER_PORT)
    logging.info(
        f"Exporter started on :{EXPORTER_PORT}, "
        f"monitoring {len(SITES)} site(s), interval={FETCH_INTERVAL}s"
    )

    while True:
        for site in SITES:
            label = site["name"]
            dl, ul = await fetch_site_data(site)
            if dl is not None and ul is not None:
                DOWNLOAD_METRIC.labels(site=label).set(dl)
                UPLOAD_METRIC.labels(site=label).set(ul)

        await asyncio.sleep(FETCH_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
