"""
Watchlist management module for Kacky Watcher.
Handles loading, saving, and validation of watchlist files.
"""
import os
import re
from typing import Set


def load_watchlist(path: str = "watchlist.txt") -> Set[int]:
    """
    Load map numbers from watchlist file.
    
    Args:
        path: Path to watchlist file
        
    Returns:
        Set of map numbers (integers)
    """
    watched: Set[int] = set()
    if not os.path.exists(path):
        return watched
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.isdigit():
                watched.add(int(line))
            else:
                # Allow formats like "379 - anything" by extracting leading number
                m = re.match(r"\s*(\d+)", line)
                if m:
                    watched.add(int(m.group(1)))
    return watched


def save_watchlist(map_numbers: Set[int], path: str = "watchlist.txt") -> None:
    """
    Save map numbers to watchlist file.
    
    Args:
        map_numbers: Set of map numbers to save
        path: Path to watchlist file
    """
    with open(path, "w", encoding="utf-8") as f:
        f.write("# One map number per line. Lines starting with # are comments.\n")
        f.write("# Examples:\n")
        for mn in sorted(map_numbers):
            f.write(f"{mn}\n")


def validate_map_number(map_str: str) -> int | None:
    """
    Validate and extract map number from string.
    
    Args:
        map_str: String that may contain a map number
        
    Returns:
        Map number as integer, or None if invalid
    """
    map_str = map_str.strip()
    if not map_str or map_str.startswith("#"):
        return None
    if map_str.isdigit():
        return int(map_str)
    # Try to extract leading number
    m = re.match(r"\s*(\d+)", map_str)
    if m:
        return int(m.group(1))
    return None

