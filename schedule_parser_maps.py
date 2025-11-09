"""
Schedule parsing module for Maps view.
Extracts map information and ETAs from the Maps tab view to calculate server uptimes.
"""
import logging
import re
from typing import Dict, List, Optional, Tuple, Any

from bs4 import BeautifulSoup


def parse_time_to_seconds(time_text: str) -> Optional[int]:
    """
    Convert time text to seconds.
    
    Supports formats:
    - "M:SS" or "MM:SS" (minutes:seconds) - e.g., "42:18", "1:42"
    - "Nh Nm" (hours and minutes) - e.g., "1h 12m"
    - "LIVE" - returns None (caller should handle)
    
    Args:
        time_text: Time string to parse
        
    Returns:
        Time in seconds, or None if cannot parse or is "LIVE"
    """
    time_text = time_text.strip()
    
    # Check for "LIVE"
    if time_text.upper() == "LIVE":
        return None
    
    # Try "M:SS" or "MM:SS" format (minutes:seconds)
    time_match = re.match(r"^(\d{1,2}):(\d{2})$", time_text)
    if time_match:
        minutes = int(time_match.group(1))
        seconds = int(time_match.group(2))
        return minutes * 60 + seconds
    
    # Try "Nh Nm" format (hours and minutes)
    hours_match = re.match(r"^(\d+)h\s*(\d+)m$", time_text)
    if hours_match:
        hours = int(hours_match.group(1))
        minutes = int(hours_match.group(2))
        return hours * 3600 + minutes * 60
    
    # Try "Nm" format (minutes only)
    minutes_match = re.match(r"^(\d+)m$", time_text)
    if minutes_match:
        minutes = int(minutes_match.group(1))
        return minutes * 60
    
    logging.debug("Could not parse time format: '%s'", time_text)
    return None


def parse_maps_view(html: str) -> List[Dict[str, Any]]:
    """
    Parse Maps view HTML to extract map ETAs and server information.
    
    The Maps view shows maps with their ETAs, allowing us to calculate server uptimes
    by comparing ETAs of consecutive maps on the same server.
    
    Structure: Each map is in a div with class containing "rounded-lg"
    - Map number: in text like "376 - ..." at the start
    - Server: in a div with text "Server X"
    - Time: in a div with time text (e.g., "42:18", "1h 12m") or "LIVE" badge
    
    Args:
        html: HTML content from Maps view
        
    Returns:
        List of dictionaries with keys:
            - map_number: Map number as string
            - server: Server label (e.g., "Server 1") or empty string if unknown
            - eta_seconds: ETA in seconds (None if LIVE or not available)
            - is_live: Boolean indicating if map is currently live
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict[str, Any]] = []
    
    # Find all map rows - they're in divs with "rounded-lg" class
    map_rows = soup.find_all("div", class_=re.compile(r"rounded-lg.*border"))
    
    if not map_rows:
        logging.warning("Could not find any map rows in Maps view HTML")
        return rows
    
    logging.debug("Found %d map rows in Maps view", len(map_rows))
    
    for row_div in map_rows:
        try:
            # Extract map number from the first part of the row
            # Look for text like "376 - ..." in font-medium div
            map_number = None
            map_info_div = row_div.find("div", class_=re.compile(r"font-medium"))
            if map_info_div:
                map_text = map_info_div.get_text(strip=True)
                # Extract number from start of text (e.g., "376 - ...")
                map_match = re.match(r"^(\d+)\s*-", map_text)
                if map_match:
                    map_number = map_match.group(1)
            
            if not map_number:
                logging.debug("Could not extract map number from row: %s", map_text[:50] if map_info_div else "no map info")
                continue
            
            # Extract server - look for div with "Server X" text
            server = ""
            server_divs = row_div.find_all("div", class_=re.compile(r"rounded-md.*bg-muted"))
            for server_div in server_divs:
                server_text = server_div.get_text(strip=True)
                server_match = re.match(r"^Server\s+(\d+)$", server_text, re.IGNORECASE)
                if server_match:
                    server = f"Server {server_match.group(1)}"
                    break
            
            if not server:
                logging.debug("Could not extract server for map %s", map_number)
                continue
            
            # Check if LIVE - look for "LIVE" badge (div with "LIVE" text)
            is_live = False
            # Look for divs with "LIVE" text (case-insensitive)
            all_divs = row_div.find_all("div")
            for div in all_divs:
                div_text = div.get_text(strip=True)
                if div_text.upper() == "LIVE":
                    is_live = True
                    break
            
            if is_live:
                eta_seconds = None
            else:
                # Extract time - look for time text in divs with emerald/yellow colors
                # Time can be in format "M:SS", "MM:SS", or "Nh Nm"
                time_divs = row_div.find_all("div", class_=re.compile(r"text-(emerald|yellow)-500"))
                eta_seconds = None
                
                for time_div in time_divs:
                    time_text = time_div.get_text(strip=True)
                    if time_text and time_text.upper() != "LIVE":
                        eta_seconds = parse_time_to_seconds(time_text)
                        if eta_seconds is not None:
                            break
                
                if eta_seconds is None:
                    # Try finding time in any div with clock icon nearby
                    clock_svg = row_div.find("svg", class_=re.compile(r"lucide-clock"))
                    if clock_svg:
                        # Find next sibling div with time text
                        parent = clock_svg.find_parent()
                        if parent:
                            time_div = parent.find("div", class_=re.compile(r"text-(emerald|yellow)"))
                            if time_div:
                                time_text = time_div.get_text(strip=True)
                                if time_text.upper() != "LIVE":
                                    eta_seconds = parse_time_to_seconds(time_text)
            
            rows.append({
                "map_number": map_number,
                "server": server,
                "eta_seconds": eta_seconds,
                "is_live": is_live
            })
            
            logging.debug("Parsed map %s: server=%s, is_live=%s, eta_seconds=%s", 
                         map_number, server, is_live, eta_seconds)
            
        except Exception as e:
            logging.warning("Error parsing Maps view row: %s", e, exc_info=True)
            continue
    
    logging.debug("Total parsed Maps view rows: %d", len(rows))
    return rows


def calculate_server_uptimes_from_maps(maps_data: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Calculate server uptimes from Maps view data.
    
    For each server, find consecutive maps and calculate uptime as:
    uptime = ETA_map_after_next - ETA_next
    
    Args:
        maps_data: List of map data from parse_maps_view()
        
    Returns:
        Dictionary of server -> uptime in seconds (rounded to nearest minute)
    """
    server_uptimes: Dict[str, int] = {}
    
    # Group maps by server (exclude LIVE maps for ETA calculation)
    maps_by_server: Dict[str, List[Tuple[int, int]]] = {}  # server -> [(map_num, eta_seconds), ...]
    
    for map_data in maps_data:
        map_num = map_data.get("map_number")
        server = map_data.get("server", "")
        eta_seconds = map_data.get("eta_seconds")
        is_live = map_data.get("is_live", False)
        
        # Skip LIVE maps and maps without ETA for uptime calculation
        if not map_num or not server or eta_seconds is None or is_live:
            continue
        
        try:
            map_num_int = int(map_num)
            if server not in maps_by_server:
                maps_by_server[server] = []
            maps_by_server[server].append((map_num_int, eta_seconds))
        except (ValueError, TypeError):
            continue
    
    # Calculate uptimes from consecutive map ETAs for each server
    for server, maps in maps_by_server.items():
        if len(maps) < 2:
            continue  # Need at least 2 maps to calculate uptime
        
        # Sort maps by ETA (ascending)
        maps.sort(key=lambda x: x[1])
        
        # Collect all uptime differences
        uptime_diffs: List[int] = []
        
        for i in range(len(maps) - 1):
            current_eta = maps[i][1]
            next_eta = maps[i + 1][1]
            
            # Uptime is the difference between consecutive map ETAs
            uptime_diff = next_eta - current_eta
            
            # Only consider reasonable uptimes (between 5 and 20 minutes)
            if 300 <= uptime_diff <= 1200:
                uptime_diffs.append(uptime_diff)
                logging.debug("Found uptime difference for %s: %d seconds from maps %d (ETA %ds) -> %d (ETA %ds)", 
                             server, uptime_diff, maps[i][0], current_eta, maps[i + 1][0], next_eta)
        
        if uptime_diffs:
            # Calculate median uptime (more robust than mean)
            uptime_diffs.sort()
            median_uptime = uptime_diffs[len(uptime_diffs) // 2]
            
            # Round to nearest minute (uptimes are always full minutes)
            uptime_minutes = round(median_uptime / 60.0)
            uptime_seconds = uptime_minutes * 60
            
            server_uptimes[server] = uptime_seconds
            logging.debug("Calculated uptime for %s: %d seconds (%d minutes) from %d differences (median)", 
                         server, uptime_seconds, uptime_minutes, len(uptime_diffs))
    
    return server_uptimes

