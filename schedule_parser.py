"""
Schedule parsing module for Kacky Watcher.
Extracts map information from HTML schedule page.
"""
import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup


def parse_live_maps(html: str) -> List[Dict[str, str]]:
    """
    Parse schedule HTML to extract map information.
    
    Args:
        html: HTML content from schedule page
        
    Returns:
        List of dictionaries with keys:
            - map_number: Map number as string
            - server: Server label (e.g., "Server 10") or empty string
            - is_live: Boolean indicating if map is currently live
            - eta: ETA time string (e.g., "10:20") or empty string
            - remaining_time: Remaining time in seconds for live maps (calculated from next map on same server)
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict[str, str]] = []

    # Heuristic: row containers usually have multiple utility classes like rounded-lg, px-3, py-2
    def has_row_like_classes(el) -> bool:
        """Check if element has CSS classes typical of schedule rows."""
        cls = el.get("class") or []
        cls_set = set(cls)
        return (
            ("rounded-lg" in cls_set or "rounded-md" in cls_set)
            and ("px-3" in cls_set or "px-2" in cls_set)
            and ("justify-between" in cls_set)
        )

    candidates = [d for d in soup.find_all("div") if has_row_like_classes(d)]
    if not candidates:
        # Broader fallback: any div that contains a Server label or LIVE badge
        for d in soup.find_all("div"):
            txt = d.get_text(" ", strip=True)
            if ("Server " in txt) or ("LIVE" in txt.upper()):
                candidates.append(d)

    seen_keys: set[str] = set()
    for row in candidates:
        # Find the first text that looks like "<num> - <something>"
        map_number = None
        for d in row.find_all(["div", "span"]):
            t = d.get_text(" ", strip=True)
            m = re.match(r"^(\d+)\s*-\s*", t)
            if m:
                map_number = m.group(1)
                break
        if not map_number:
            # Try direct row text too
            t = row.get_text(" ", strip=True)
            m = re.match(r"^(\d+)\s*-\s*", t)
            if m:
                map_number = m.group(1)
        if not map_number:
            continue

        # Determine LIVE state and extract server/ETA anywhere within this row
        is_live = False
        server_label = ""
        eta_text = ""
        for d in row.find_all(["div", "span"]):
            t = d.get_text(" ", strip=True)
            if not server_label and t.startswith("Server "):
                server_label = t
            if "LIVE" in t.upper():
                is_live = True
            # Pick up ETA like 0:47, 10:20, 1:03, 30:47, etc.
            if not eta_text:
                mt = re.match(r"^(\d{1,2}):(\d{2})$", t)
                if mt:
                    eta_text = t

        # Clean server label if the time (ETA) or LIVE got concatenated in same element
        if server_label:
            server_label = re.sub(r"\s*\b\d{1,2}:\d{2}\b", "", server_label)
            server_label = re.sub(r"\s*\bLIVE\b", "", server_label, flags=re.IGNORECASE)
            server_label = server_label.strip()

        key = f"{map_number}:{server_label}:{is_live}"
        if key in seen_keys:
            continue
        seen_keys.add(key)

        rows.append({"map_number": map_number, "server": server_label, "is_live": is_live, "eta": eta_text, "remaining_time": ""})

    # Calculate remaining time for live maps by finding next map on same server
    # Group rows by server
    rows_by_server: Dict[str, List[Dict[str, str]]] = {}
    for row in rows:
        server = row.get("server", "") or ""
        if server:
            rows_by_server.setdefault(server, []).append(row)
    
    # For each live map, find the next upcoming map on the same server
    for row in rows:
        if row.get("is_live") and row.get("server"):
            server = row["server"]
            if server in rows_by_server:
                # Find the next upcoming map on this server (has ETA, not live)
                next_eta_seconds: Optional[int] = None
                for other_row in rows_by_server[server]:
                    if other_row == row:
                        continue  # Skip self
                    if not other_row.get("is_live") and other_row.get("eta"):
                        eta_text = other_row["eta"]
                        m = re.match(r"^(\d{1,2}):(\d{2})$", eta_text)
                        if m:
                            sec = int(m.group(1)) * 60 + int(m.group(2))
                            if next_eta_seconds is None or sec < next_eta_seconds:
                                next_eta_seconds = sec
                
                # Set remaining time if found
                if next_eta_seconds is not None:
                    row["remaining_time"] = str(next_eta_seconds)
                # If no next map found, remaining_time stays empty (will use default)

    return rows

