"""
Settings management module for Kacky Watcher.
Handles loading and saving settings from/to JSON file.
"""
import json
import os
import logging
from typing import Dict, Any, Optional

from path_utils import get_settings_file


SETTINGS_FILE = "settings.json"  # For backward compatibility, actual path comes from get_settings_file()


def get_default_settings() -> Dict[str, Any]:
    """Get default settings dictionary."""
    return {
        # User-facing settings
        "LOG_LEVEL": "INFO",
        "ENABLE_NOTIFICATIONS": True,  # Windows toast notifications
        # Internal settings (not shown in GUI)
        "REQUEST_TIMEOUT_SECONDS": 10,
        "USER_AGENT": "KackyWatcher/1.0 (+https://kacky.gg/schedule)",
        "WATCHLIST_REFRESH_SECONDS": 20,
        "LIVE_DURATION_SECONDS": 600,  # Fallback duration when time not available from website
    }


def load_settings() -> Dict[str, Any]:
    """
    Load settings from JSON file, or return defaults if file doesn't exist.
    Removes deprecated settings and ensures only current settings are loaded.
    
    Returns:
        Dictionary containing all settings with appropriate types.
    """
    settings_path = get_settings_file()
    defaults = get_default_settings()
    
    if not os.path.exists(settings_path):
        return defaults
    
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        
        # List of deprecated settings to remove
        deprecated_settings = [
            "CHECK_INTERVAL_SECONDS",
            "ENABLE_BROWSER",  # Always use browser now
            "ETA_MARGIN_SECONDS",  # Not used anymore
            "ETA_FETCH_THRESHOLD_SECONDS",  # Not used anymore
        ]
        
        # Remove deprecated settings
        for key in deprecated_settings:
            if key in loaded:
                del loaded[key]
                logging.debug(f"Removed deprecated setting: {key}")
        
        # Merge with defaults to ensure all keys exist and add any missing defaults
        result = defaults.copy()
        result.update(loaded)
        
        # Ensure internal settings are preserved (they might not be in old settings files)
        for key in ["USER_AGENT", "REQUEST_TIMEOUT_SECONDS", "WATCHLIST_REFRESH_SECONDS", "LIVE_DURATION_SECONDS"]:
            if key not in result:
                result[key] = defaults[key]
        
        return result
    except (json.JSONDecodeError, IOError) as e:
        logging.warning(f"Error loading settings file: {e}. Using defaults.")
        return defaults


def save_settings(settings: Dict[str, Any]) -> bool:
    """
    Save settings to JSON file.
    Removes deprecated settings before saving.
    
    Args:
        settings: Settings dictionary to save
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Remove deprecated settings before saving
        deprecated_settings = [
            "CHECK_INTERVAL_SECONDS",
            "ENABLE_BROWSER",  # Always use browser now
            "ETA_MARGIN_SECONDS",  # Not used anymore
            "ETA_FETCH_THRESHOLD_SECONDS",  # Not used anymore
        ]
        
        cleaned_settings = settings.copy()
        for key in deprecated_settings:
            cleaned_settings.pop(key, None)
        
        settings_path = get_settings_file()
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(cleaned_settings, f, indent=2, ensure_ascii=False)
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

