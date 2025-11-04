"""
Configuration management module for Kacky Watcher.
Loads settings from JSON file (settings.json) with defaults.
"""
import logging
import os
import sys
from typing import Dict, Any

from settings_manager import load_settings

# Track if logging has been initialized (to reset log file only on first init)
_logging_initialized = False


def get_log_file_path() -> str:
    """
    Get the path to the log file.
    In EXE mode, uses the directory of the EXE. Otherwise uses current directory.
    
    Returns:
        Path to log.txt file
    """
    if getattr(sys, 'frozen', False):
        # EXE mode - use directory of EXE
        return os.path.join(os.path.dirname(sys.executable), "log.txt")
    else:
        # Development mode - use current directory
        return os.path.join(os.getcwd(), "log.txt")


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
    Logs to both console and log.txt file.
    
    Args:
        level_name: Log level name (e.g., "INFO", "DEBUG", "WARNING")
    """
    global _logging_initialized
    
    level = getattr(logging, level_name, logging.INFO)
    
    # Clear any existing handlers to avoid duplicates
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S"
    )
    
    # Console handler (for development/debugging)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(console_formatter)
    
    # Add console handler first (so we can log errors if file handler fails)
    root_logger.addHandler(console_handler)
    root_logger.setLevel(level)
    
    # File handler (log.txt)
    try:
        log_file_path = get_log_file_path()
        # On first initialization, reset the log file (mode='w')
        # On subsequent calls (e.g., log level change), append to existing log (mode='a')
        file_mode = 'w' if not _logging_initialized else 'a'
        file_handler = logging.FileHandler(log_file_path, mode=file_mode, encoding='utf-8')
        file_handler.setLevel(level)
        file_handler.setFormatter(detailed_formatter)
        root_logger.addHandler(file_handler)
        if not _logging_initialized:
            logging.info(f"Logging to file: {log_file_path}")
        else:
            logging.debug(f"Log level changed to {level_name}, continuing to log to: {log_file_path}")
        _logging_initialized = True
    except Exception as e:
        # If we can't create log file, just log to console
        logging.warning(f"Could not create log file: {e}")

