"""
Configuration management module for Kacky Watcher.
Loads settings from JSON file (settings.json) with defaults.
"""
import logging
from typing import Dict, Any

from settings_manager import load_settings


def load_config() -> Dict[str, Any]:
    """
    Load configuration from settings.json file or use defaults.
    
    Returns:
        Dictionary containing all configuration settings with appropriate types.
    """
    settings = load_settings()
    # Ensure LOG_LEVEL is uppercase
    if "LOG_LEVEL" in settings:
        settings["LOG_LEVEL"] = settings["LOG_LEVEL"].upper()
    return settings


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

