"""
Map status management module for Kacky Watcher.
Handles persistence of tracking and finished map states via JSON.
"""
import json
import os
from typing import Dict, Set, Optional

from path_utils import get_map_status_file


DEFAULT_STATUS_FILE = "map_status.json"  # For backward compatibility, actual path comes from get_map_status_file()


def load_map_status(path: str = None) -> Dict:
    """
    Load map status from JSON file.
    
    Args:
        path: Path to JSON file (if None, uses default from path_utils)
        
    Returns:
        Dictionary with keys:
            - "tracking": Set of tracked map numbers
            - "finished": Set of finished map numbers
            - "server_uptimes": Dict of server -> uptime in seconds (optional)
    """
    if path is None:
        path = get_map_status_file()
    
    if not os.path.exists(path):
        return {"tracking": set(), "finished": set(), "server_uptimes": {}}
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {
                "tracking": set(data.get("tracking", [])),
                "finished": set(data.get("finished", [])),
                "server_uptimes": data.get("server_uptimes", {}),
            }
    except (json.JSONDecodeError, IOError):
        return {"tracking": set(), "finished": set(), "server_uptimes": {}}


def save_map_status(
    tracking: Set[int], 
    finished: Set[int], 
    path: str = None,
    server_uptimes: Optional[Dict[str, int]] = None
) -> None:
    """
    Save map status to JSON file.
    
    Args:
        tracking: Set of tracked map numbers
        finished: Set of finished map numbers
        path: Path to JSON file (if None, uses default from path_utils)
        server_uptimes: Optional dict of server uptimes (server -> seconds)
    """
    if path is None:
        path = get_map_status_file()
    
    # Load existing data to preserve server_uptimes if not provided
    existing_data = load_map_status(path)
    if server_uptimes is None:
        server_uptimes = existing_data.get("server_uptimes", {})
    
    data = {
        "tracking": sorted(tracking),
        "finished": sorted(finished),
        "server_uptimes": server_uptimes,
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


def get_server_uptimes(path: str = None) -> Dict[str, int]:
    """
    Get server uptimes from map status file.
    
    Args:
        path: Path to JSON file (if None, uses default from path_utils)
        
    Returns:
        Dictionary of server -> uptime in seconds
    """
    status = load_map_status(path)
    return status.get("server_uptimes", {})

