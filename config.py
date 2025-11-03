"""
Configuration management module for Kacky Watcher.
Loads settings from environment variables via .env file.
"""
import os
import logging
from typing import Dict, Any

from dotenv import load_dotenv


def load_config() -> Dict[str, Any]:
    """
    Load configuration from environment variables.
    
    Returns:
        Dictionary containing all configuration settings with appropriate types.
    """
    load_dotenv()  # loads from .env in cwd if present
    check_interval = int(os.getenv("CHECK_INTERVAL_SECONDS", "20"))
    request_timeout = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "10"))
    user_agent = os.getenv("USER_AGENT", "KackyWatcher/1.0 (+https://kacky.gg/schedule)")
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    enable_browser = os.getenv("ENABLE_BROWSER", "0") in ("1", "true", "TRUE", "yes", "on")
    watchlist_refresh = int(os.getenv("WATCHLIST_REFRESH_SECONDS", "20"))
    eta_margin = int(os.getenv("ETA_MARGIN_SECONDS", "2"))
    eta_fetch_threshold = int(os.getenv("ETA_FETCH_THRESHOLD_SECONDS", "60"))
    live_duration_seconds = int(os.getenv("LIVE_DURATION_SECONDS", "600"))
    return {
        "CHECK_INTERVAL_SECONDS": check_interval,
        "REQUEST_TIMEOUT_SECONDS": request_timeout,
        "USER_AGENT": user_agent,
        "LOG_LEVEL": log_level,
        "ENABLE_BROWSER": enable_browser,
        "WATCHLIST_REFRESH_SECONDS": watchlist_refresh,
        "ETA_MARGIN_SECONDS": eta_margin,
        "ETA_FETCH_THRESHOLD_SECONDS": eta_fetch_threshold,
        "LIVE_DURATION_SECONDS": live_duration_seconds,
    }


def setup_logging(level_name: str) -> None:
    """
    Configure Python logging with the specified level.
    
    Args:
        level_name: Log level name (e.g., "INFO", "DEBUG", "WARNING")
    """
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

