"""
Schedule parsing module for Kacky Watcher.
Extracts map information from HTML schedule page.
"""
import logging
import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup


def parse_live_maps(html: str) -> List[Dict[str, str]]:
    """
    Parse schedule HTML to extract map information.
    
    New format: Table with columns:
    - Server number (#)
    - Active map (Now)
    - Next 3 maps (Next Maps)
    - Remaining time (Time)
    
    Args:
        html: HTML content from schedule page
        
    Returns:
        List of dictionaries with keys:
            - map_number: Map number as string
            - server: Server label (e.g., "Server 1") or empty string
            - is_live: Boolean indicating if map is currently live
            - eta: ETA time string (e.g., "10:20") or empty string
            - remaining_time: Remaining time in seconds for live maps
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict[str, str]] = []
    
    # Find the table
    table = soup.find("table", {"data-slot": "table"})
    if not table:
        # Fallback: try to find any table
        table = soup.find("table")
    
    if not table:
        logging.warning("Could not find schedule table in HTML")
        return rows
    
    # Find tbody with table rows
    tbody = table.find("tbody", {"data-slot": "table-body"})
    if not tbody:
        tbody = table.find("tbody")
    
    if not tbody:
        logging.warning("Could not find table body in schedule table")
        return rows
    
    # Iterate through table rows
    table_rows = tbody.find_all("tr", {"data-slot": "table-row"})
    if not table_rows:
        # Fallback: try without data-slot attribute
        table_rows = tbody.find_all("tr")
    
    for tr in table_rows:
        cells = tr.find_all("td", {"data-slot": "table-cell"})
        if len(cells) < 4:
            # Try without data-slot attribute
            cells = tr.find_all("td")
            if len(cells) < 4:
                logging.debug("Skipping row with < 4 cells")
                continue
        
        try:
            # Column 1: Server number
            server_cell = cells[0]
            server_badge = server_cell.find("span", {"data-slot": "badge"})
            if not server_badge:
                server_badge = server_cell.find("span")
            
            server_num = None
            if server_badge:
                server_text = server_badge.get_text(strip=True)
                # Extract number from badge (e.g., "1", "2", "10")
                server_match = re.match(r"^(\d+)$", server_text)
                if server_match:
                    server_num = server_match.group(1)
            
            if not server_num:
                logging.debug("Skipping row: could not extract server number from cell: %s", server_cell.get_text(strip=True)[:50])
                continue  # Skip rows without valid server number
            
            server_label = f"Server {server_num}"
            
            # Column 2: Active/Live map (Now column)
            now_cell = cells[1]
            live_map_link = now_cell.find("a", href=re.compile(r"/map/\d+"))
            if not live_map_link:
                logging.debug("Skipping row Server %s: could not find live map link in 'Now' column", server_num)
                continue  # Skip if no live map found
            
            live_map_text = live_map_link.get_text(strip=True)
            live_map_match = re.match(r"^(\d+)$", live_map_text)
            if not live_map_match:
                logging.debug("Skipping row Server %s: live map text '%s' does not match map number pattern", server_num, live_map_text)
                continue
            
            live_map_num = live_map_match.group(1)
            
            # Column 4: Remaining time
            # Extract time from the time cell (4th column)
            time_cell = cells[3]
            
            # Get all text from the time cell and search for time pattern
            # Time format: "M:SS" or "MM:SS" (e.g., "5:07", "2:11", "1:05")
            cell_text = time_cell.get_text(" ", strip=True)
            
            # Search for time pattern in the cell text
            time_match = re.search(r"(\d{1,2}):(\d{2})", cell_text)
            remaining_seconds = None
            time_text = ""
            needs_retry = False
            
            if time_match:
                time_text = time_match.group(0)
                minutes = int(time_match.group(1))
                seconds = int(time_match.group(2))
                remaining_seconds = minutes * 60 + seconds
                logging.debug("Server %s: extracted time '%s' (%d seconds) from cell text: '%s'", 
                            server_num, time_text, remaining_seconds, cell_text[:50])
            else:
                # Time cell is empty - this happens during map transitions
                # Use default duration (10 minutes = 600 seconds) and mark for retry
                logging.debug("Server %s (map %s): time cell is empty (transitioning?), using default duration. Cell text: '%s'", 
                            server_num, live_map_num, cell_text[:100])
                remaining_seconds = 600  # Default 10 minutes
                needs_retry = True
            
            # Column 3: Next maps (upcoming maps) - parse these even if time is missing
            next_maps_cell = cells[2]
            next_map_links = next_maps_cell.find_all("a", href=re.compile(r"/map/\d+"))
            
            # Add the live map (always add, even if time is missing)
            rows.append({
                "map_number": live_map_num,
                "server": server_label,
                "is_live": True,
                "eta": "",  # Live maps don't have ETA
                "remaining_time": str(remaining_seconds) if remaining_seconds is not None else "",
                "needs_retry": needs_retry  # Flag to indicate this map needs a retry fetch
            })
            
            # Calculate ETAs for next maps
            # If we have a valid time, use it; otherwise use default duration
            base_eta_seconds = remaining_seconds if remaining_seconds is not None else 600
            
            for idx, next_map_link in enumerate(next_map_links):
                next_map_text = next_map_link.get_text(strip=True)
                next_map_match = re.match(r"^(\d+)$", next_map_text)
                if not next_map_match:
                    logging.debug("Skipping next map link in Server %s: text '%s' does not match map number pattern", 
                                server_num, next_map_text)
                    continue
                
                next_map_num = next_map_match.group(1)
                
                # Calculate ETA: first map = remaining_time, each subsequent = +10 minutes
                # If time was missing, ETAs are estimates
                eta_seconds = base_eta_seconds + (idx * 600)  # 600 seconds = 10 minutes
                
                # Convert to M:SS format
                eta_minutes = eta_seconds // 60
                eta_secs = eta_seconds % 60
                eta_text = f"{eta_minutes}:{eta_secs:02d}"
                
                rows.append({
                    "map_number": next_map_num,
                    "server": server_label,
                    "is_live": False,
                    "eta": eta_text,
                    "remaining_time": ""  # Not live, so no remaining time
                    # Note: needs_retry only applies to live maps, not upcoming maps
                })
            
            if needs_retry:
                logging.debug("Parsed Server %s: live map %s (transitioning, needs retry), next maps: %s", 
                            server_num, live_map_num, 
                            [link.get_text(strip=True) for link in next_map_links])
            else:
                logging.debug("Parsed Server %s: live map %s (remaining: %ds), next maps: %s", 
                            server_num, live_map_num, remaining_seconds, 
                            [link.get_text(strip=True) for link in next_map_links])
        except Exception as e:
            logging.warning("Error parsing table row: %s", e, exc_info=True)
            continue
    
    logging.debug("Total parsed rows: %d", len(rows))
    return rows
