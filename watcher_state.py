"""
State management module for Kacky Watcher.
Tracks ETAs, live windows, servers, and notification state.
"""
import logging
import time
import re
from typing import Dict, List, Set, Tuple, Optional


class WatcherState:
    """
    Manages the internal state of the watcher including:
    - ETAs for tracked maps
    - Live map persistence windows
    - Server information
    - Notification tracking
    """
    
    def __init__(self, live_duration_seconds: int = 600):
        """
        Initialize watcher state.
        
        Args:
            live_duration_seconds: How long to keep maps in "live" state after detection
        """
        self.live_duration_seconds = live_duration_seconds
        # Predicted ETAs and servers between fetches
        self.eta_seconds_by_map: Dict[int, int] = {}
        self.server_by_map: Dict[int, str] = {}
        # Persist live state for a period (maps are ~10 minutes live)
        self.live_until_by_map: Dict[int, float] = {}
        self.live_servers_by_map: Dict[int, Set[str]] = {}
        # Track multiple upcoming per map (server, seconds)
        self.upcoming_by_map: Dict[int, List[Tuple[str, int]]] = {}
        # Remember which watched maps are currently live to avoid repeat notifications
        self.notified_live: Set[int] = set()
        
        # Server uptime tracking (in seconds, always full minutes)
        # Initialize with known defaults:
        # Servers 1-4: 10 minutes (600 seconds)
        # Servers 5-8: 13 minutes (780 seconds)
        # Servers 9-10: 15 minutes (900 seconds)
        self.server_uptime_seconds: Dict[str, int] = {}
        for server_num in range(1, 5):
            self.server_uptime_seconds[f"Server {server_num}"] = 600  # 10 minutes
        for server_num in range(5, 9):
            self.server_uptime_seconds[f"Server {server_num}"] = 780  # 13 minutes
        for server_num in range(9, 11):
            self.server_uptime_seconds[f"Server {server_num}"] = 900  # 15 minutes
    
    def update_from_fetch(self, rows: List[Dict[str, str]], watched: Set[int]) -> Set[int]:
        """
        Update state from fetched schedule data.
        ONLY updates times/ETAs - does NOT change live/tracked state.
        State transitions are handled locally (tracked -> live when ETA hits 0).
        
        Args:
            rows: Parsed schedule rows from HTML
            watched: Set of watched map numbers
            
        Returns:
            Set of map numbers that are currently live (for reference only)
        """
        now_ts = time.time()
        live_now: Set[int] = set()  # For reference only
        
        # Track maps we have local state for
        maps_with_local_state = set(self.eta_seconds_by_map.keys()) | set(self.live_until_by_map.keys())
        
        for r in rows:
            try:
                mn = int(r.get("map_number", "0"))
            except ValueError:
                continue
            if mn not in watched:
                continue
            srv = r.get("server", "") or ""
            
            if r.get("is_live"):
                remaining_time_str = r.get("remaining_time", "") or ""
                needs_retry = r.get("needs_retry", False)
                
                # Skip maps with empty time cells (transitioning) - handle locally
                # When needs_retry is True, the parser used server_uptime as a placeholder
                # We shouldn't update state with placeholder data, but we can learn from real data
                if needs_retry:
                    # The parser set remaining_time to server_uptime as a placeholder
                    # Don't update state with this placeholder - handle locally using server uptime
                    logging.debug("Map #%s has empty time cell (transitioning), skipping time update (will use server uptime locally)", mn)
                    # Still add to live_now for reference, but don't update live_until_by_map
                    live_now.add(mn)
                    continue
                
                # Update server uptime knowledge from observed data (only if we have real data)
                if remaining_time_str and remaining_time_str.isdigit():
                    remaining_seconds = int(remaining_time_str)
                    # Learn server uptime from observed remaining time
                    # Maps that just went live have close to full uptime
                    if remaining_seconds > 0:
                        self.update_server_uptime(srv, remaining_seconds)
                
                # Update live time if map is already live locally
                if mn in self.live_until_by_map:
                    if remaining_time_str and remaining_time_str.isdigit():
                        remaining_seconds = int(remaining_time_str)
                        self.live_until_by_map[mn] = now_ts + remaining_seconds
                        logging.debug("Map #%s live time synced: remaining %ds", mn, remaining_seconds)
                    if srv:
                        self.live_servers_by_map.setdefault(mn, set()).add(srv)
                # Only add to live state if we don't have local state for it (new map)
                elif mn not in maps_with_local_state:
                    # New map - add to live state
                    if remaining_time_str and remaining_time_str.isdigit():
                        remaining_seconds = int(remaining_time_str)
                        self.live_until_by_map[mn] = now_ts + remaining_seconds
                        logging.debug("Map #%s added to live state (new map): remaining %ds", mn, remaining_seconds)
                    else:
                        # Use server's uptime instead of default duration
                        server_uptime = self.get_server_uptime(srv)
                        self.live_until_by_map[mn] = now_ts + server_uptime
                        logging.debug("Map #%s added to live state (new map): server uptime %ds", mn, server_uptime)
                    if srv:
                        self.live_servers_by_map.setdefault(mn, set()).add(srv)
                # If map is in tracked (has ETA), don't change state - it will transition locally when ETA hits 0
                elif mn in self.eta_seconds_by_map:
                    logging.debug("Map #%s is tracked locally, keeping tracked state (will transition locally)", mn)
                    # Don't change state - keep it tracked, it will go live when ETA hits 0 locally
                
                live_now.add(mn)  # For reference
            else:
                # Map is not live on website - update ETA if we have one
                eta = r.get("eta", "") or ""
                if eta:
                    m = re.match(r"^(\d{1,2}):(\d{2})$", eta)
                    if m:
                        sec = int(m.group(1)) * 60 + int(m.group(2))
                        
                        # Update ETA if map is already tracked
                        if mn in self.eta_seconds_by_map:
                            # Update to sync time
                            self.eta_seconds_by_map[mn] = sec
                            self.server_by_map[mn] = srv
                            logging.debug("Map #%s ETA synced: %ds", mn, sec)
                        # Only add to tracked if we don't have local state for it (new map)
                        elif mn not in maps_with_local_state:
                            # New map - add to tracked
                            self.eta_seconds_by_map[mn] = sec
                            self.server_by_map[mn] = srv
                            logging.debug("Map #%s added to tracked state (new map): ETA %ds", mn, sec)
                        
                        # Update per-server list
                        if srv:
                            self.upcoming_by_map.setdefault(mn, [])
                            existing = {s: t for s, t in self.upcoming_by_map[mn]}
                            if (srv not in existing) or (sec < existing[srv]):
                                existing[srv] = sec
                                self.upcoming_by_map[mn] = sorted(existing.items(), key=lambda x: x[1])
                        
                        # If map was live, don't remove it - it will transition locally when time expires
                        # Just update ETA for when it goes live again (or add ETA if it doesn't have one)
                        if mn in self.live_until_by_map:
                            logging.debug("Map #%s is live locally, keeping live state (will transition locally)", mn)
                            # Don't change state - keep it live, it will go to tracked when time expires locally
        
        return live_now  # For reference only - state is managed locally
    
    def countdown_etas(self, decrement_seconds: int) -> None:
        """
        Decrement all ETA predictions by the specified amount.
        Called between fetches to simulate countdown.
        
        Args:
            decrement_seconds: How many seconds to subtract from each ETA
        """
        for k in list(self.eta_seconds_by_map.keys()):
            self.eta_seconds_by_map[k] = max(0, self.eta_seconds_by_map[k] - decrement_seconds)
        
        for mn, items in list(self.upcoming_by_map.items()):
            updated = []
            for s, t in items:
                new_t = max(0, t - decrement_seconds)
                updated.append((s, new_t))
            self.upcoming_by_map[mn] = updated
    
    def cleanup_expired_live_windows(self, now_ts: float) -> None:
        """
        Remove expired live windows from state.
        
        Args:
            now_ts: Current timestamp
        """
        for mn in list(self.live_until_by_map.keys()):
            if self.live_until_by_map[mn] <= now_ts:
                del self.live_until_by_map[mn]
                self.live_servers_by_map.pop(mn, None)
    
    def get_live_summary(self, watched: Set[int], live_now: Set[int], now_ts: float) -> List[int]:
        """
        Get list of maps that should be shown as "live" in summary.
        
        Args:
            watched: Set of watched map numbers
            live_now: Set of maps currently live from latest fetch (if empty, means no recent fetch)
            now_ts: Current timestamp
            
        Returns:
            Sorted list of map numbers that are live
        """
        self.cleanup_expired_live_windows(now_ts)
        live_summary: List[int] = []
        
        # If we have a recent fetch (live_now is not empty), use it as source of truth
        # If live_now is empty, we're using cached state, so use live windows
        if live_now:
            # Recent fetch: only show maps that are actually live now
            # Remove any maps from live_until_by_map that are not in live_now
            for mn in list(self.live_until_by_map.keys()):
                if mn not in live_now:
                    del self.live_until_by_map[mn]
                    self.live_servers_by_map.pop(mn, None)
            # If a map is in live_now (from recent fetch), it's currently live on the website
            live_summary = sorted(live_now & watched)
        else:
            # No recent fetch: use live windows for persistence
            for mn in sorted(watched):
                if mn in self.live_until_by_map and self.live_until_by_map[mn] > now_ts:
                    live_summary.append(mn)
        
        return live_summary
    
    def get_nearest_eta(self, watched: Set[int], threshold_sec: int, now_ts: float) -> Tuple[int, List[Tuple[int, int, str]]]:
        """
        Calculate the nearest ETA among watched maps, excluding live maps.
        
        Args:
            watched: Set of watched map numbers
            threshold_sec: ETA threshold in seconds
            now_ts: Current timestamp
            
        Returns:
            Tuple of (nearest_eta_seconds, list of triggering maps as (map_num, eta_sec, server))
        """
        nearest_eta = 10**9
        triggering_maps: List[Tuple[int, int, str]] = []
        
        try:
            candidates = []
            # First, check non-live maps (only watched ones)
            for mn, sec in self.eta_seconds_by_map.items():
                if sec > 0 and mn in watched:
                    # Skip if this map is currently live
                    if mn not in self.live_until_by_map or self.live_until_by_map[mn] <= now_ts:
                        candidates.append(sec)
                        if sec <= threshold_sec:
                            triggering_maps.append((mn, sec, self.server_by_map.get(mn, "")))
            # Also check upcoming servers for live maps (if they're below threshold and watched)
            for mn, items in self.upcoming_by_map.items():
                if mn in watched and mn in self.live_until_by_map and self.live_until_by_map[mn] > now_ts:
                    # This map is live and watched, check if any upcoming server is below threshold
                    for s, t in items:
                        if t > 0 and t <= threshold_sec:
                            candidates.append(t)
                            triggering_maps.append((mn, t, s))
                            break  # only need one below threshold to trigger
            if candidates:
                nearest_eta = min(candidates)
        except ValueError:
            pass
        
        return nearest_eta, triggering_maps
    
    def has_expiring_live_windows(self, now_ts: float, threshold_sec: int, margin_sec: int = 5, watched: Optional[Set[int]] = None) -> bool:
        """
        Check if any live windows are expiring soon.
        
        Args:
            now_ts: Current timestamp
            threshold_sec: ETA threshold in seconds
            margin_sec: Additional margin in seconds
            watched: Optional set of watched map numbers to filter by
            
        Returns:
            True if any live window (for watched maps if specified) expires within threshold + margin
        """
        for mn, until_ts in self.live_until_by_map.items():
            # Only check watched maps if watched set is provided
            if watched is not None and mn not in watched:
                continue
            if until_ts <= now_ts + threshold_sec + margin_sec:
                return True
        return False
    
    def get_newly_live(self, watched: Set[int], live_now: Set[int]) -> Set[int]:
        """
        Get maps that are newly live (not previously notified).
        
        Args:
            watched: Set of watched map numbers
            live_now: Set of maps currently live from latest fetch
            
        Returns:
            Set of newly live map numbers
        """
        return (watched & live_now) - self.notified_live
    
    def mark_notified(self, map_numbers: Set[int]) -> None:
        """
        Mark map numbers as notified.
        
        Args:
            map_numbers: Set of map numbers to mark as notified
        """
        self.notified_live.update(map_numbers)
    
    def clear_notifications_for(self, map_numbers: Set[int]) -> None:
        """
        Clear notifications for maps that are no longer live.
        
        Args:
            map_numbers: Set of map numbers to clear
        """
        self.notified_live -= map_numbers
    
    def get_next_live_window_expiry(self, now_ts: float, watched: Optional[Set[int]] = None) -> Optional[float]:
        """
        Get the timestamp when the next live window expires.
        
        Args:
            now_ts: Current timestamp
            watched: Optional set of watched map numbers to filter by
            
        Returns:
            Timestamp of next expiry, or None if no live windows (for watched maps if specified)
        """
        if not self.live_until_by_map:
            return None
        
        # Filter by watched maps if provided
        relevant_expiries = []
        for mn, until_ts in self.live_until_by_map.items():
            if watched is None or mn in watched:
                relevant_expiries.append(until_ts)
        
        if not relevant_expiries:
            return None
        return min(relevant_expiries)
    
    def get_next_eta_expiry(self, watched: Set[int], now_ts: float) -> Optional[int]:
        """
        Get the seconds until the next ETA expires (hits 0).
        
        Args:
            watched: Set of watched map numbers
            now_ts: Current timestamp
            
        Returns:
            Seconds until next ETA expires, or None if no ETAs
        """
        candidates = []
        # Check single ETAs
        for mn, sec in self.eta_seconds_by_map.items():
            if mn in watched and sec > 0:
                # Skip if this map is currently live
                if mn not in self.live_until_by_map or self.live_until_by_map[mn] <= now_ts:
                    candidates.append(sec)
        
        # Check upcoming servers for live maps
        for mn, items in self.upcoming_by_map.items():
            if mn in watched:
                # Check if map is live
                is_live = mn in self.live_until_by_map and self.live_until_by_map[mn] > now_ts
                if is_live:
                    # Map is live, check upcoming servers
                    for s, t in items:
                        if t > 0:
                            candidates.append(t)
                            break
                else:
                    # Map not live, check ETAs
                    for s, t in items:
                        if t > 0:
                            candidates.append(t)
        
        if not candidates:
            return None
        return min(candidates)
    
    def update_server_uptime(self, server: str, observed_remaining_time: int) -> None:
        """
        Update server uptime based on observed remaining time.
        Uptimes are always full minutes (10, 12, 15, etc.), so we learn from maps that
        just went live (which have close to full uptime remaining).
        
        Args:
            server: Server label (e.g., "Server 1")
            observed_remaining_time: Observed remaining time in seconds
        """
        if not server or observed_remaining_time <= 0:
            return
        
        # Convert to minutes (rounding to nearest)
        observed_minutes_float = observed_remaining_time / 60.0
        observed_minutes = round(observed_minutes_float)
        observed_seconds = observed_minutes * 60
        
        current_uptime = self.server_uptime_seconds.get(server, 600)
        current_minutes = current_uptime // 60
        
        # Only update if:
        # 1. Observed time is within 30 seconds of a full minute (maps start with ~full uptime)
        # 2. The rounded minutes value is close to or higher than current uptime
        # 3. Observed time is at least 95% of current uptime (to avoid updates from mid-cycle observations)
        
        time_diff_from_full_minute = abs(observed_seconds - observed_remaining_time)
        
        # Check if observed time is close to a full minute (within 30 seconds)
        is_close_to_full_minute = time_diff_from_full_minute <= 30
        
        # Check if this looks like a map that just went live (high remaining time)
        is_high_remaining_time = observed_remaining_time >= current_uptime * 0.95
        
        if is_close_to_full_minute and (observed_seconds >= current_uptime or is_high_remaining_time):
            # Only update if the new value is higher, or if it's very close to current (within 1 minute)
            if observed_seconds > current_uptime or (observed_seconds >= current_uptime * 0.95 and observed_seconds <= current_uptime * 1.05):
                self.server_uptime_seconds[server] = observed_seconds
                logging.debug("Updated server %s uptime to %d seconds (%d minutes) (observed %d seconds, %.1f minutes)", 
                             server, observed_seconds, observed_minutes, observed_remaining_time, observed_minutes_float)
    
    def get_server_uptime(self, server: str) -> int:
        """
        Get uptime for a server, falling back to default if unknown.
        
        Args:
            server: Server label (e.g., "Server 1")
            
        Returns:
            Uptime in seconds (always a full minute)
        """
        if not server:
            return 600  # Default fallback
        return self.server_uptime_seconds.get(server, 600)

