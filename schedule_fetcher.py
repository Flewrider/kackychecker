"""
Schedule fetching module for Kacky Watcher.
Handles HTTP requests and optional headless browser fetching.
"""
import logging
from typing import Optional

import requests

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


SCHEDULE_URL = "https://kacky.gg/schedule"


def fetch_schedule_html(user_agent: Optional[str] = None, timeout: int = 10) -> str:
    """
    Fetch schedule HTML using HTTP GET request.
    
    Args:
        user_agent: Optional User-Agent header string
        timeout: Request timeout in seconds
        
    Returns:
        HTML content as string
        
    Raises:
        requests.HTTPError: If HTTP request fails
        requests.RequestException: If network error occurs
    """
    headers = {"User-Agent": user_agent or "KackyWatcher/1.0 (+https://kacky.gg/schedule)"}
    resp = requests.get(SCHEDULE_URL, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def fetch_schedule_html_browser(timeout: int = 20, user_agent: Optional[str] = None) -> str:
    """
    Fetch schedule HTML using headless browser (Playwright).
    Used when site requires client-side rendering.
    
    Args:
        timeout: Page load timeout in seconds
        user_agent: Optional User-Agent string
        
    Returns:
        HTML content as string
        
    Raises:
        ImportError: If Playwright is not installed
        Exception: If browser operation fails
    """
    if not PLAYWRIGHT_AVAILABLE:
        raise ImportError("Playwright not available. Install with: pip install playwright && python -m playwright install")
    
    logging.debug("Starting Playwright browser fetch...")
    logging.debug("PLAYWRIGHT_AVAILABLE: %s", PLAYWRIGHT_AVAILABLE)
    logging.debug("Timeout: %d seconds", timeout)
    
    try:
        logging.debug("Creating Playwright context...")
        with sync_playwright() as p:
            logging.debug("Launching Chromium browser...")
            browser = p.chromium.launch(headless=True)
            logging.debug("Browser launched successfully")
            try:
                logging.debug("Creating browser context...")
                context = browser.new_context(user_agent=user_agent or "KackyWatcher/1.0 (+https://kacky.gg/schedule)")
                logging.debug("Creating new page...")
                page = context.new_page()
                page.set_default_timeout(timeout * 1000)
                
                logging.debug("Navigating to %s...", SCHEDULE_URL)
                page.goto(SCHEDULE_URL, wait_until="domcontentloaded")
                logging.debug("Page loaded, waiting for dynamic content...")
                
                # Wait briefly for dynamic content; look for either LIVE badge or Server label
                try:
                    page.wait_for_selector(r"text=/LIVE|Server \d+/", timeout=timeout * 1000)
                    logging.debug("Dynamic content selector found")
                except Exception as e:
                    logging.warning("Timeout waiting for dynamic content selector: %s", e)
                    # Timeout is acceptable, continue with what we have
                
                logging.debug("Getting page content...")
                html = page.content()
                logging.debug("Retrieved page content: %d characters", len(html))
                return html
            finally:
                logging.debug("Closing browser...")
                browser.close()
                logging.debug("Browser closed")
    except Exception as e:
        logging.error("Error in browser fetch: %s", e, exc_info=True)
        raise

