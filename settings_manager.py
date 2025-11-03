"""
Settings management module for Kacky Watcher.
Handles loading and saving settings from/to JSON file.
"""
import json
import os
import logging
from typing import Dict, Any, Optional


SETTINGS_FILE = "settings.json"


def get_default_settings() -> Dict[str, Any]:
    """Get default settings dictionary."""
    return {
        "CHECK_INTERVAL_SECONDS": 20,
        "REQUEST_TIMEOUT_SECONDS": 10,
        "USER_AGENT": "KackyWatcher/1.0 (+https://kacky.gg/schedule)",
        "LOG_LEVEL": "INFO",
        "ENABLE_BROWSER": True,
        "WATCHLIST_REFRESH_SECONDS": 20,
        "ETA_MARGIN_SECONDS": 2,
        "ETA_FETCH_THRESHOLD_SECONDS": 60,
        "LIVE_DURATION_SECONDS": 600,
        "ENABLE_NOTIFICATIONS": True,  # Windows toast notifications
    }


def load_settings() -> Dict[str, Any]:
    """
    Load settings from JSON file, or return defaults if file doesn't exist.
    
    Returns:
        Dictionary containing all settings with appropriate types.
    """
    if not os.path.exists(SETTINGS_FILE):
        return get_default_settings()
    
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        
        # Merge with defaults to ensure all keys exist
        defaults = get_default_settings()
        defaults.update(loaded)
        return defaults
    except (json.JSONDecodeError, IOError) as e:
        logging.warning(f"Error loading settings file: {e}. Using defaults.")
        return get_default_settings()


def save_settings(settings: Dict[str, Any]) -> bool:
    """
    Save settings to JSON file.
    
    Args:
        settings: Settings dictionary to save
        
    Returns:
        True if successful, False otherwise
    """
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        return True
    except IOError as e:
        logging.error(f"Error saving settings file: {e}")
        return False


def update_setting(key: str, value: Any) -> None:
    """
    Update a single setting and save to file.
    
    Args:
        key: Setting key
        value: Setting value
    """
    settings = load_settings()
    settings[key] = value
    save_settings(settings)

