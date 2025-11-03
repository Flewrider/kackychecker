"""
Map status management module for Kacky Watcher.
Handles persistence of tracking and finished map states via JSON.
"""
import json
import os
from typing import Dict, Set

from path_utils import get_map_status_file


DEFAULT_STATUS_FILE = "map_status.json"  # For backward compatibility, actual path comes from get_map_status_file()


def load_map_status(path: str = None) -> Dict[str, Set[int]]:
    """
    Load map status from JSON file.
    
    Args:
        path: Path to JSON file (if None, uses default from path_utils)
        
    Returns:
        Dictionary with keys:
            - "tracking": Set of tracked map numbers
            - "finished": Set of finished map numbers
    """
    if path is None:
        path = get_map_status_file()
    
    if not os.path.exists(path):
        return {"tracking": set(), "finished": set()}
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {
                "tracking": set(data.get("tracking", [])),
                "finished": set(data.get("finished", [])),
            }
    except (json.JSONDecodeError, IOError):
        return {"tracking": set(), "finished": set()}


def save_map_status(tracking: Set[int], finished: Set[int], path: str = None) -> None:
    """
    Save map status to JSON file.
    
    Args:
        tracking: Set of tracked map numbers
        finished: Set of finished map numbers
        path: Path to JSON file (if None, uses default from path_utils)
    """
    if path is None:
        path = get_map_status_file()
    
    data = {
        "tracking": sorted(tracking),
        "finished": sorted(finished),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_tracking_maps(path: str = None) -> Set[int]:
    """
    Get set of tracked maps.
    
    Args:
        path: Path to JSON file (if None, uses default from path_utils)
        
    Returns:
        Set of tracked map numbers
    """
    status = load_map_status(path)
    return status["tracking"]


def get_finished_maps(path: str = None) -> Set[int]:
    """
    Get set of finished maps.
    
    Args:
        path: Path to JSON file (if None, uses default from path_utils)
        
    Returns:
        Set of finished map numbers
    """
    status = load_map_status(path)
    return status["finished"]

