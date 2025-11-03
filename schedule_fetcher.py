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
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(user_agent=user_agent or "KackyWatcher/1.0 (+https://kacky.gg/schedule)")
            page = context.new_page()
            page.set_default_timeout(timeout * 1000)
            page.goto(SCHEDULE_URL, wait_until="domcontentloaded")
            # Wait briefly for dynamic content; look for either LIVE badge or Server label
            try:
                page.wait_for_selector(r"text=/LIVE|Server \d+/", timeout=timeout * 1000)
            except Exception:
                pass  # Timeout is acceptable, continue with what we have
            html = page.content()
            return html
        finally:
            browser.close()

