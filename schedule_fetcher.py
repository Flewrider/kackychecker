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


def fetch_schedule_html_browser(timeout: int = 20, user_agent: Optional[str] = None, view: str = "servers") -> str:
    """
    Fetch schedule HTML using headless browser (Playwright).
    Used when site requires client-side rendering.
    
    Args:
        timeout: Page load timeout in seconds
        user_agent: Optional User-Agent string
        view: Which view to fetch - "servers" (default) or "maps"
        
    Returns:
        HTML content as string
        
    Raises:
        ImportError: If Playwright is not installed
        Exception: If browser operation fails
    """
    if not PLAYWRIGHT_AVAILABLE:
        raise ImportError("Playwright not available. Install with: pip install playwright && python -m playwright install")
    
    logging.debug("Starting Playwright browser fetch... (view: %s)", view)
    logging.debug("PLAYWRIGHT_AVAILABLE: %s", PLAYWRIGHT_AVAILABLE)
    logging.debug("Timeout: %d seconds", timeout)
    
    try:
        logging.debug("Creating Playwright context...")
        with sync_playwright() as p:
            logging.debug("Launching Chromium browser...")
            # Launch browser - Playwright 1.48.0+ automatically uses new headless mode
            # Note: Playwright 1.47.0 uses old headless mode which newer Chromium doesn't support
            # This EXE needs to be rebuilt with Playwright 1.49.0+ to work with newer Chromium versions
            browser = p.chromium.launch(headless=True)
            logging.debug("Browser launched successfully")
            try:
                logging.debug("Creating browser context...")
                context = browser.new_context(user_agent=user_agent or "KackyWatcher/1.0 (+https://kacky.gg/schedule)")
                logging.debug("Creating new page...")
                page = context.new_page()
                page.set_default_timeout(timeout * 1000)
                
                logging.debug("Navigating to %s...", SCHEDULE_URL)
                # Use domcontentloaded for fast initial load
                page.goto(SCHEDULE_URL, wait_until="domcontentloaded", timeout=timeout * 1000)
                logging.debug("DOM loaded")
                
                # Wait for the table element that we actually parse (short timeout)
                # This ensures the dynamic content is rendered without waiting too long
                table_found = False
                try:
                    page.wait_for_selector("table[data-slot='table'], table", timeout=2000)
                    logging.debug("Schedule table found")
                    table_found = True
                except Exception:
                    # Table not found immediately - wait a bit for JS to render
                    logging.debug("Table not found immediately, waiting for JS to render...")
                    page.wait_for_timeout(1500)  # Wait 1.5 seconds for JS to render
                
                # If table was found quickly, give JS a moment to finish rendering data
                if table_found:
                    page.wait_for_timeout(500)  # Brief wait to ensure data is populated
                
                # Switch to Maps view if requested
                if view == "maps":
                    logging.debug("Switching to Maps view...")
                    try:
                        # Find and click the "Maps" button
                        # Button structure: <button>Maps</button> in the tab switcher
                        maps_button = page.locator("button:has-text('Maps')").first
                        if maps_button.is_visible(timeout=2000):
                            # Click the button
                            maps_button.click()
                            logging.debug("Clicked Maps button")
                            # Wait for the table to update (wait for any table changes)
                            page.wait_for_timeout(1500)  # Wait for view to update and data to load
                            # Verify we're in Maps view by checking if table structure changed
                            # (The table should still exist, but content should be different)
                            logging.debug("Maps view should be loaded")
                        else:
                            logging.warning("Maps button not found, using default view")
                    except Exception as e:
                        logging.warning("Failed to switch to Maps view: %s, using default view", e)
                
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

