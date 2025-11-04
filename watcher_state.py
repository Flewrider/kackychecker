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
        # Track maps that recently reached 0:00 (cooldown period to exclude from live tab)
        # Maps are excluded from live display for 5 minutes after reaching 0:00
        self.recently_finished_by_map: Dict[int, float] = {}
    
    def update_from_fetch(self, rows: List[Dict[str, str]], watched: Set[int]) -> Set[int]:
        """
        Update state from fetched schedule data.
        
        Args:
            rows: Parsed schedule rows from HTML
            watched: Set of watched map numbers
            
        Returns:
            Set of map numbers that are currently live
        """
        now_ts = time.time()
        live_now: Set[int] = set()
        
        # Track which maps were live before this update
        previously_live = set(self.live_until_by_map.keys())
        
        # Clear ETA caches
        self.eta_seconds_by_map.clear()
        self.server_by_map.clear()
        self.upcoming_by_map.clear()
        
        for r in rows:
            try:
                mn = int(r.get("map_number", "0"))
            except ValueError:
                continue
            srv = r.get("server", "") or ""
            
            if r.get("is_live"):
                # Check if map is in cooldown period - if so, ignore it even if website says it's live
                cooldown_until = self.recently_finished_by_map.get(mn, 0)
                if cooldown_until > now_ts:
                    logging.debug("Map #%s is in cooldown period (until %s), ignoring live status from website", mn, cooldown_until - now_ts)
                    continue  # Skip this map, don't add it to live_now or live_until_by_map
                
                logging.debug("Map #%s detected as live, adding to live_now", mn)
                live_now.add(mn)
                # Only set live window if newly live (not already tracked)
                if mn not in self.live_until_by_map:
                    # Use calculated remaining time if available, otherwise use default duration
                    remaining_time_str = r.get("remaining_time", "") or ""
                    if remaining_time_str and remaining_time_str.isdigit():
                        remaining_seconds = int(remaining_time_str)
                        self.live_until_by_map[mn] = now_ts + remaining_seconds
                    else:
                        # Fall back to default duration
                        self.live_until_by_map[mn] = now_ts + self.live_duration_seconds
                if srv:
                    self.live_servers_by_map.setdefault(mn, set()).add(srv)
                # Remove from ETA tracking since it's live on this server
                self.eta_seconds_by_map.pop(mn, None)
                self.server_by_map.pop(mn, None)
                # Only remove upcoming entries for the server where it's live
                if mn in self.upcoming_by_map and srv:
                    self.upcoming_by_map[mn] = [(s, t) for s, t in self.upcoming_by_map[mn] if s != srv]
                    if not self.upcoming_by_map[mn]:
                        del self.upcoming_by_map[mn]
            else:
                # Track ETA for upcoming maps
                eta = r.get("eta", "") or ""
                if eta:
                    m = re.match(r"^(\d{1,2}):(\d{2})$", eta)
                    if m:
                        sec = int(m.group(1)) * 60 + int(m.group(2))
                        # Store single-earliest summary
                        if (mn not in self.eta_seconds_by_map) or (sec < self.eta_seconds_by_map[mn]):
                            self.eta_seconds_by_map[mn] = sec
                            self.server_by_map[mn] = srv
                        # Store per-server list
                        if srv:
                            self.upcoming_by_map.setdefault(mn, [])
                            # Keep only earliest per server
                            existing = {s: t for s, t in self.upcoming_by_map[mn]}
                            if (srv not in existing) or (sec < existing[srv]):
                                # Rebuild list with updated server time
                                existing[srv] = sec
                                self.upcoming_by_map[mn] = sorted(existing.items(), key=lambda x: x[1])
        
        # Remove maps from live_until_by_map that are no longer live
        # (they were live before but aren't in live_now now)
        no_longer_live = previously_live - live_now
        for mn in no_longer_live:
            if mn in self.live_until_by_map:
                del self.live_until_by_map[mn]
            if mn in self.live_servers_by_map:
                del self.live_servers_by_map[mn]
            # If map just finished (was live but no longer in live_now), mark it for cooldown
            # Only mark if not already in cooldown (to avoid resetting cooldown timer)
            if mn not in self.recently_finished_by_map or self.recently_finished_by_map[mn] <= now_ts:
                self.recently_finished_by_map[mn] = now_ts + 300  # 5 minutes cooldown
                logging.debug("Map #%s no longer live, removed from live window and starting 5-minute cooldown", mn)
            else:
                logging.debug("Map #%s no longer live, removed from live window (already in cooldown)", mn)
        
        return live_now
    
    def countdown_etas(self, decrement_seconds: int) -> None:
        """
        Decrement all ETA predictions by the specified amount.
        Called between fetches to simulate countdown.
        
        Args:
            decrement_seconds: How many seconds to subtract from each ETA
        """
        now_ts = time.time()
        for k in list(self.eta_seconds_by_map.keys()):
            old_value = self.eta_seconds_by_map[k]
            self.eta_seconds_by_map[k] = max(0, self.eta_seconds_by_map[k] - decrement_seconds)
            # If ETA just reached 0, mark map as recently finished (5 minute cooldown)
            if old_value > 0 and self.eta_seconds_by_map[k] == 0:
                self.recently_finished_by_map[k] = now_ts + 300  # 5 minutes cooldown
                logging.debug("Map #%s reached 0:00, starting 5-minute cooldown period", k)
        
        for mn, items in list(self.upcoming_by_map.items()):
            updated = []
            for s, t in items:
                old_t = t
                new_t = max(0, t - decrement_seconds)
                updated.append((s, new_t))
                # If ETA just reached 0, mark map as recently finished
                if old_t > 0 and new_t == 0:
                    self.recently_finished_by_map[mn] = now_ts + 300  # 5 minutes cooldown
                    logging.debug("Map #%s reached 0:00 on server %s, starting 5-minute cooldown period", mn, s)
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
                # Mark map for cooldown when its live window expires
                # Only mark if not already in cooldown (to avoid resetting cooldown timer)
                if mn not in self.recently_finished_by_map or self.recently_finished_by_map[mn] <= now_ts:
                    self.recently_finished_by_map[mn] = now_ts + 300  # 5 minutes cooldown
                    logging.debug("Map #%s live window expired, marking for 5-minute cooldown", mn)
        
        # Clean up expired cooldown entries
        for mn in list(self.recently_finished_by_map.keys()):
            if self.recently_finished_by_map[mn] <= now_ts:
                del self.recently_finished_by_map[mn]
    
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
            # Filter out maps in cooldown period (recently finished)
            # If a map is in live_now (from recent fetch), it's currently live on the website
            # We only need to check cooldown, not live window (since live_now is source of truth)
            live_summary = []
            for mn in sorted(live_now & watched):
                cooldown_until = self.recently_finished_by_map.get(mn, 0)
                if cooldown_until <= now_ts:
                    live_summary.append(mn)
                else:
                    logging.debug("Map #%s in live_now but filtered out due to cooldown (until %s)", mn, cooldown_until - now_ts)
            live_summary = sorted(live_summary)
        else:
            # No recent fetch: use live windows for persistence
            for mn in sorted(watched):
                if mn in self.live_until_by_map and self.live_until_by_map[mn] > now_ts:
                    # Exclude maps in cooldown period
                    if self.recently_finished_by_map.get(mn, 0) <= now_ts:
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

