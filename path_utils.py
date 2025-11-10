"""
Path utilities for Kacky Watcher.
Handles EXE vs development mode path detection.
"""
import os
import sys
from pathlib import Path


def get_data_directory() -> str:
    """
    Get the directory where data files should be stored.
    
    In EXE mode (PyInstaller), returns the directory containing the EXE.
    In development mode, returns the current working directory.
    
    Returns:
        Path to data directory as string
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled EXE (PyInstaller)
        # sys.executable is the path to the EXE file
        return os.path.dirname(sys.executable)
    else:
        # Running as script
        return os.getcwd()


def get_settings_file() -> str:
    """Get path to settings.json file."""
    return os.path.join(get_data_directory(), "settings.json")


def get_map_status_file() -> str:
    """Get path to map_status.json file."""
    return os.path.join(get_data_directory(), "map_status.json")

