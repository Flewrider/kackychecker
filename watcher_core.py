"""
Core watcher logic module for Kacky Watcher.
Handles polling loop, fetch decisions, and state management.
"""
import os
import re
import time
import logging
from typing import Dict, List, Set, Tuple, Callable, Optional, Any

from config import load_config, setup_logging
from schedule_fetcher import fetch_schedule_html, fetch_schedule_html_browser
from schedule_parser import parse_live_maps
from map_status_manager import get_tracking_maps
from watcher_state import WatcherState
from path_utils import get_map_status_file


class KackyWatcher:
    """
    Main watcher class that handles polling and state management.
    Uses callbacks to communicate with GUI or CLI.
    """
    
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        on_status_update: Optional[Callable[[str], None]] = None,
        on_live_notification: Optional[Callable[[int, str], None]] = None,
        on_summary_update: Optional[Callable[[List[int], List[tuple]], None]] = None,
    ):
        """
        Initialize watcher.
        
        Args:
            config: Configuration dictionary (if None, loads from settings.json)
            on_status_update: Callback(status_message: str) for status updates
            on_live_notification: Callback(map_number: int, server: str) for live notifications
            on_summary_update: Callback(live_maps: List[int], tracked_lines: List[tuple[int, str]]) for summary
        """
        self.config = config or load_config()
        setup_logging(self.config["LOG_LEVEL"])
        
        self.on_status_update = on_status_update or (lambda msg: None)
        self.on_live_notification = on_live_notification or (lambda mn, srv: None)
        self.on_summary_update = on_summary_update or (lambda live, tracked: None)
        
        self.state = WatcherState(self.config["LIVE_DURATION_SECONDS"])
        self.status_file = get_map_status_file()
        self.last_status_mtime = os.path.getmtime(self.status_file) if os.path.exists(self.status_file) else 0.0
        self.last_status_check = 0.0
        self.watchlist_added = False
        self.last_fetch_time = 0.0  # Track when we last fetched to prevent rapid refetches
        self.last_successful_fetch_time = 0.0  # Track when we last successfully fetched data
        self.consecutive_fetch_failures = 0  # Track consecutive fetch failures
        self.live_map_resync_times: Dict[int, float] = {}  # Track when to resync live maps (1 minute after going live)
        self.periodic_refetch_time: float = 0.0  # Track when to do periodic refetch (for unknown time maps and staleness)
        self.initial_fetch_done = False  # Track if initial fetch has been done
        self.watched: Set[int] = get_tracking_maps(self.status_file)
        
        if not self.watched:
            logging.warning("No maps are being tracked. Check maps in the GUI to start tracking.")
        
        logging.debug("Watching %d map(s): %s", len(self.watched), ", ".join(map(str, sorted(self.watched))) if self.watched else "<none>")
        logging.debug("Using dynamic polling based on map ETAs and live windows")
    
    def reload_status(self) -> bool:
        """
        Reload map status if file changed.
        
        Returns:
            True if status was reloaded and new maps were added
        """
        now = time.time()
        if now - self.last_status_check < self.config["WATCHLIST_REFRESH_SECONDS"]:
            return False
        
        self.last_status_check = now
        try:
            mtime = os.path.getmtime(self.status_file) if os.path.exists(self.status_file) else 0.0
            if mtime and mtime != self.last_status_mtime:
                prev_watched = set(self.watched)
                self.watched = get_tracking_maps(self.status_file)
                self.last_status_mtime = mtime
                logging.debug("Reloaded map status: %s", sorted(self.watched))
                added = self.watched - prev_watched
                if added:
                    logging.debug("New map(s) added: %s", sorted(added))
                    self.watchlist_added = True
                    return True
        except Exception:
            logging.debug("Could not stat/reload map status.")
        
        return False
    
    def should_fetch(self, now_ts: float) -> Tuple[bool, Optional[str], List[Tuple[int, int, str]]]:
        """
        Determine if we should fetch the schedule.
        Fetches are ONLY for syncing times, not for state transitions.
        State transitions (tracked -> live, live -> tracked) are handled locally.
        
        Args:
            now_ts: Current timestamp
            
        Returns:
            Tuple of (should_fetch: bool, fetch_reason: str | None, triggering_maps: List)
        """
        fetch_reason = None
        triggering_maps = []
        
        # 1. Initial fetch (only once) - to get initial state
        if not self.initial_fetch_done:
            fetch_reason = "initial"
            should_fetch = True
            logging.debug("Fetch decision: initial fetch (first run)")
            return should_fetch, fetch_reason, triggering_maps
        
        # 2. Map added with no data - fetch to get ETA/live status
        if self.watchlist_added:
            # Check if we have data for the new maps
            new_maps = self.watched - set(self.state.eta_seconds_by_map.keys()) - set(self.state.live_until_by_map.keys())
            if new_maps:
                fetch_reason = "watchlist_added"
                should_fetch = True
                logging.debug("Fetch decision: new maps added with no data: %s", sorted(new_maps))
                return should_fetch, fetch_reason, triggering_maps
        
        # 3. Resync time for live maps (1 minute after going live) - to sync remaining time
        maps_needing_resync = []
        for mn, resync_time in list(self.live_map_resync_times.items()):
            if now_ts >= resync_time:
                maps_needing_resync.append(mn)
        
        if maps_needing_resync:
            fetch_reason = "live_resync"
            should_fetch = True
            logging.debug("Fetch decision: resync time for live maps: %s", sorted(maps_needing_resync))
            return should_fetch, fetch_reason, triggering_maps
        
        # 4. Periodic refetch for unknown time maps and staleness prevention
        # Check if we have tracked maps with no ETA (unknown time)
        has_unknown_time_maps = False
        if self.watched:
            for mn in self.watched:
                # Map is tracked but has no ETA and is not live
                if (mn not in self.state.eta_seconds_by_map and 
                    mn not in self.state.live_until_by_map):
                    has_unknown_time_maps = True
                    break
        
        # Schedule periodic refetch if not already scheduled
        # Every 60 seconds if unknown time maps, or every 5 minutes for staleness prevention
        if self.periodic_refetch_time == 0.0:
            if has_unknown_time_maps:
                # More frequent refetch for unknown time maps
                self.periodic_refetch_time = now_ts + 60.0
                logging.debug("Scheduled periodic refetch in 60s (unknown time maps detected)")
            elif self.last_successful_fetch_time > 0:
                # Periodic refetch every 5 minutes to prevent staleness
                self.periodic_refetch_time = now_ts + 300.0
                logging.debug("Scheduled periodic refetch in 300s (staleness prevention)")
            # If last_successful_fetch_time is 0, we haven't fetched yet - wait for initial fetch
        
        # Check if it's time for periodic refetch
        if self.periodic_refetch_time > 0 and now_ts >= self.periodic_refetch_time:
            fetch_reason = "periodic_refetch"
            should_fetch = True
            if has_unknown_time_maps:
                logging.debug("Fetch decision: periodic refetch for unknown time maps")
            else:
                logging.debug("Fetch decision: periodic refetch for staleness prevention")
            return should_fetch, fetch_reason, triggering_maps
        
        # No fetch needed - all state transitions are handled locally
        should_fetch = False
        logging.debug("Fetch decision: no fetch needed (all state handled locally)")
        return should_fetch, fetch_reason, triggering_maps
    
    def calculate_next_fetch_time(self, now_ts: float) -> float:
        """
        Calculate how many seconds until the next fetch is needed.
        Fetches are only for syncing times (initial, new maps, resync).
        
        Args:
            now_ts: Current timestamp
            
        Returns:
            Seconds until next fetch (0 if immediate fetch needed, max 300 seconds)
        """
        # If watchlist was added, fetch immediately
        if self.watchlist_added:
            return 0.0
        
        # Check for earliest resync time
        if self.live_map_resync_times:
            earliest_resync = min(self.live_map_resync_times.values())
            if earliest_resync <= now_ts:
                return 0.0
            time_until_resync = earliest_resync - now_ts
            # Don't return more than periodic refetch time
            if self.periodic_refetch_time > 0:
                time_until_periodic = self.periodic_refetch_time - now_ts
                return min(time_until_resync, max(0.0, time_until_periodic), 300.0)
            return min(time_until_resync, 300.0)
        
        # Check for periodic refetch time
        if self.periodic_refetch_time > 0:
            if self.periodic_refetch_time <= now_ts:
                return 0.0
            time_until_periodic = self.periodic_refetch_time - now_ts
            return min(time_until_periodic, 300.0)
        
        # No fetch needed soon, use a reasonable default (5 minutes)
        return 300.0
    
    def fetch_schedule(self) -> List[Dict[str, str]]:
        """
        Fetch and parse schedule HTML.
        
        Returns:
            List of parsed schedule rows
        """
        logging.debug("=== fetch_schedule() called ===")
        rows: List[Dict[str, str]] = []
        
        logging.debug("Starting schedule fetch...")
        logging.debug("ENABLE_BROWSER setting: %s", self.config.get("ENABLE_BROWSER", True))
        
        # Try browser first since HTTP requests don't work for this site
        # (site requires JavaScript rendering)
        if self.config.get("ENABLE_BROWSER", True):
            logging.debug("Attempting browser fetch (Playwright)...")
            try:
                html = fetch_schedule_html_browser(
                    timeout=self.config["REQUEST_TIMEOUT_SECONDS"] * 2,
                    user_agent=self.config["USER_AGENT"]
                )
                logging.debug("[browser] Fetched %d chars of HTML", len(html))
                if len(html) < 100:
                    logging.warning("[browser] HTML content seems very short: %d chars", len(html))
                rows = parse_live_maps(html)
                logging.debug("[browser] Parsed %d schedule rows", len(rows))
            except Exception as e:
                logging.error("Browser fetch failed: %s", e, exc_info=True)
                # Fall back to HTTP if browser fails
                logging.debug("Falling back to HTTP fetch...")
                try:
                    html = fetch_schedule_html(self.config["USER_AGENT"], self.config["REQUEST_TIMEOUT_SECONDS"])
                    logging.debug("Fetched %d chars of HTML (fallback)", len(html))
                    rows = parse_live_maps(html)
                    logging.debug("Parsed %d schedule rows (fallback)", len(rows))
                except Exception as e2:
                    logging.error("HTTP fallback also failed: %s", e2, exc_info=True)
        else:
            # Browser disabled, try HTTP only
            logging.debug("Browser disabled, using HTTP fetch only...")
            try:
                html = fetch_schedule_html(self.config["USER_AGENT"], self.config["REQUEST_TIMEOUT_SECONDS"])
                logging.debug("Fetched %d chars of HTML", len(html))
                rows = parse_live_maps(html)
                logging.debug("Parsed %d schedule rows", len(rows))
            except Exception as e:
                logging.error("HTTP fetch failed: %s", e, exc_info=True)
        
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            for i, r in enumerate(rows[:50]):  # cap to avoid flooding
                logging.debug("Row %02d → map=%s server='%s' live=%s eta=%s", 
                            i + 1, r.get("map_number"), r.get("server", ""), r.get("is_live"), r.get("eta", ""))
        
        if not rows:
            logging.warning("Parsed 0 rows — site structure may have changed or browser not installed.")
            logging.warning("This may indicate: 1) Website structure changed, 2) Browser not working, 3) Network issue")
        else:
            logging.debug("Successfully fetched and parsed %d schedule rows", len(rows))
        
        return rows
    
    def format_summary(self, rows: List[Dict[str, str]], did_fetch: bool, live_now: Optional[Set[int]] = None) -> Tuple[List[int], List[Tuple[int, str]]]:
        """
        Format summary data for display.
        
        Args:
            rows: Parsed schedule rows
            did_fetch: Whether we fetched this cycle
            live_now: Set of live maps from update_from_fetch
            
        Returns:
            Tuple of (live_summary: List[int], tracked_lines: List[tuple[int, str]])
        """
        def eta_to_seconds(eta: str) -> int:
            m = re.match(r"^(\d{1,2}):(\d{2})$", eta)
            if not m:
                return 10**9
            return int(m.group(1)) * 60 + int(m.group(2))
        
        # Build earliest ETA per watched map when not live
        earliest_eta_by_map: Dict[int, Dict[str, str]] = {}
        for r in rows:
            try:
                mn = int(r.get("map_number", "0"))
            except ValueError:
                continue
            if mn not in self.watched:
                continue
            if r.get("is_live"):
                continue
            eta = r.get("eta", "") or ""
            if not eta:
                continue
            cur = earliest_eta_by_map.get(mn)
            if cur is None or eta_to_seconds(eta) < eta_to_seconds(cur.get("eta", "999:59")):
                earliest_eta_by_map[mn] = {"eta": eta, "server": r.get("server", "")}
        
        # Determine live maps for summary
        # Use live_now passed from update_from_fetch
        # If not provided, build from rows (fallback for non-fetch cycles)
        now_ts = time.time()
        if live_now is None:
            if did_fetch:
                # Fallback: build from rows (but this shouldn't happen if live_now is passed)
                live_now = {int(r.get("map_number", "0")) for r in rows if r.get("is_live")}
                live_now = {mn for mn in live_now if mn in self.watched and mn > 0}
            else:
                live_now = set()
        live_summary = self.state.get_live_summary(self.watched, live_now, now_ts)
        
        # Build tracked lines
        tracked_lines: List[Tuple[int, str]] = []
        BIG = 10**9
        
        # First, add non-live maps
        for mn in sorted(set(self.watched) - set(live_summary)):
            eta_sec = BIG
            line = f"- {mn} will be live in unknown"
            
            info = earliest_eta_by_map.get(mn)
            if did_fetch and info:
                m = re.match(r"^(\d{1,2}):(\d{2})$", info.get("eta", ""))
                if m:
                    eta_sec = int(m.group(1)) * 60 + int(m.group(2))
                if info.get("server"):
                    line = f"- {mn} will be live in {info['eta']} on {info['server']}"
                else:
                    line = f"- {mn} will be live in {info['eta']}"
            else:
                # Use predicted ETA if available
                if mn in self.state.upcoming_by_map and self.state.upcoming_by_map[mn]:
                    s, sec = self.state.upcoming_by_map[mn][0]
                    eta_sec = sec
                    if s:
                        line = f"- {mn} will be live in {sec//60}:{sec%60:02d} on {s}"
                    else:
                        line = f"- {mn} will be live in {sec//60}:{sec%60:02d}"
                elif mn in self.state.eta_seconds_by_map:
                    sec = self.state.eta_seconds_by_map[mn]
                    eta_sec = sec
                    srv = self.state.server_by_map.get(mn, "")
                    if srv:
                        line = f"- {mn} will be live in {sec//60}:{sec%60:02d} on {srv}"
                    else:
                        line = f"- {mn} will be live in {sec//60}:{sec%60:02d}"
            
            tracked_lines.append((eta_sec, line))
        
        # Also add upcoming servers for live maps
        for mn in live_summary:
            if mn in self.state.upcoming_by_map and self.state.upcoming_by_map[mn]:
                for s, sec in self.state.upcoming_by_map[mn]:
                    tracked_lines.append((sec, f"- {mn} will be live in {sec//60}:{sec%60:02d} on {s}"))
        
        return live_summary, tracked_lines
    
    def poll_once(self, force_fetch: bool = False) -> None:
        """
        Execute one polling cycle.
        All state transitions (tracked -> live, live -> tracked) are handled locally.
        Fetches are ONLY for syncing times (initial state, new maps, resync after 1min).
        
        Args:
            force_fetch: If True, force a fetch regardless of should_fetch logic
        """
        try:
            logging.debug("Starting poll cycle…")
            
            # Reload map status if needed
            self.reload_status()
            
            now_ts = time.time()
            rows: List[Dict[str, str]] = []
            did_fetch = False
            
            # Countdown ETAs and live times locally (do this first)
            self.state.countdown_etas(1)  # Countdown by 1 second
            
            # Handle tracked maps whose ETA has reached 0 - automatically mark as live locally
            expired_etas = []
            for mn in self.watched:
                # Check if map's ETA has hit 0 and it's not already live
                if mn in self.state.eta_seconds_by_map and self.state.eta_seconds_by_map[mn] <= 0:
                    if mn not in self.state.live_until_by_map or self.state.live_until_by_map[mn] <= now_ts:
                        expired_etas.append(mn)
                # Check upcoming servers
                if mn in self.state.upcoming_by_map:
                    for srv, sec in self.state.upcoming_by_map[mn]:
                        if sec <= 0:
                            if mn not in self.state.live_until_by_map or self.state.live_until_by_map[mn] <= now_ts:
                                if mn not in expired_etas:
                                    expired_etas.append(mn)
                                break
            
            # Automatically mark expired ETAs as live locally (no fetch needed)
            for mn in expired_etas:
                if mn not in self.state.live_until_by_map or self.state.live_until_by_map[mn] <= now_ts:
                    # Mark as live with default duration
                    self.state.live_until_by_map[mn] = now_ts + self.state.live_duration_seconds
                    # Schedule resync fetch 1 minute after going live
                    self.live_map_resync_times[mn] = now_ts + 60.0
                    logging.debug("Map #%s ETA expired locally, marked as live (resync in 60s)", mn)
                    # Get server from state if available
                    server = self.state.server_by_map.get(mn, "")
                    if server:
                        self.state.live_servers_by_map.setdefault(mn, set()).add(server)
                    # Remove from ETA tracking since it's now live
                    # Keep upcoming_by_map for other servers, but remove the primary ETA
                    self.state.eta_seconds_by_map.pop(mn, None)
                    # Remove server from upcoming if it matches
                    if mn in self.state.upcoming_by_map and server:
                        self.state.upcoming_by_map[mn] = [(s, t) for s, t in self.state.upcoming_by_map[mn] if s != server]
                        if not self.state.upcoming_by_map[mn]:
                            del self.state.upcoming_by_map[mn]
                    # Notify if this is newly live
                    if mn not in self.state.notified_live:
                        self.on_live_notification(mn, server)
                        self.state.mark_notified({mn})
                        logging.debug("KACKY MAP LIVE: #%s on %s", mn, server if server else "<unknown server>")
            
            # Check if we should fetch (simplified logic)
            if force_fetch:
                should_fetch = True
                fetch_reason = "forced"
            else:
                should_fetch, fetch_reason, _ = self.should_fetch(now_ts)
            
            # Fetch if needed
            if should_fetch:
                # Prevent rapid refetches (minimum 2 seconds between fetches)
                min_fetch_interval = 2.0
                if now_ts - self.last_fetch_time < min_fetch_interval:
                    if fetch_reason not in ("initial", "watchlist_added", "forced"):
                        should_fetch = False
                        logging.debug("Skipping fetch (too soon after last fetch: %.1fs)", now_ts - self.last_fetch_time)
                
                if should_fetch:
                    # Log fetch reason and update status
                    if fetch_reason == "initial":
                        logging.debug("Fetching schedule (reason: initial state)")
                        self.on_status_update("Fetching schedule (initial state)...")
                    elif fetch_reason == "watchlist_added":
                        logging.debug("Fetching schedule (reason: new map added with no data)")
                        self.on_status_update("Fetching schedule (new map added)...")
                    elif fetch_reason == "live_resync":
                        logging.debug("Fetching schedule (reason: resync time for live maps)")
                        self.on_status_update("Resyncing live map times...")
                    elif fetch_reason == "periodic_refetch":
                        logging.debug("Fetching schedule (reason: periodic refetch)")
                        self.on_status_update("Periodic refetch...")
                    
                    # Fetch schedule
                    try:
                        rows = self.fetch_schedule()
                        logging.debug("fetch_schedule() returned with %d rows", len(rows))
                        did_fetch = True
                        self.last_fetch_time = now_ts
                        self.initial_fetch_done = True
                        
                        # Track successful fetches
                        if rows:
                            self.last_successful_fetch_time = now_ts
                            self.consecutive_fetch_failures = 0
                        else:
                            self.consecutive_fetch_failures += 1
                            if self.consecutive_fetch_failures >= 2:
                                time_since_success = now_ts - self.last_successful_fetch_time if self.last_successful_fetch_time > 0 else float('inf')
                                if time_since_success > 60:
                                    self.on_status_update(f"⚠️ Website unreachable or returned no data (last success: {int(time_since_success)}s ago)")
                                else:
                                    self.on_status_update("⚠️ Website unreachable or returned no data")
                    except Exception as e:
                        logging.error("Exception in fetch_schedule(): %s", e, exc_info=True)
                        rows = []
                        did_fetch = True
                        self.last_fetch_time = now_ts
                        self.initial_fetch_done = True
            
            # Update state from fetch if we fetched (only syncs times, doesn't change state)
            if did_fetch:
                # Update times from fetched data (doesn't change live/tracked state)
                self.state.update_from_fetch(rows, self.watched)
                
                # Clear resync times for maps that were resynced (they were just fetched)
                if fetch_reason == "live_resync":
                    for mn in list(self.live_map_resync_times.keys()):
                        if now_ts >= self.live_map_resync_times[mn]:
                            del self.live_map_resync_times[mn]
                            logging.debug("Cleared resync time for map #%s after resync fetch", mn)
                
                # Update periodic refetch timer after successful fetch
                # Check if we have unknown time maps (maps with no ETA and not live)
                has_unknown_time_maps = False
                if self.watched:
                    for mn in self.watched:
                        if (mn not in self.state.eta_seconds_by_map and 
                            mn not in self.state.live_until_by_map):
                            has_unknown_time_maps = True
                            break
                
                if fetch_reason == "periodic_refetch":
                    # Reset timer - will be recalculated on next should_fetch call
                    self.periodic_refetch_time = 0.0
                    logging.debug("Reset periodic refetch timer after fetch")
                elif self.periodic_refetch_time == 0.0 or fetch_reason == "initial":
                    # Initialize or reset periodic refetch timer
                    if has_unknown_time_maps:
                        # More frequent refetch for unknown time maps (60 seconds)
                        self.periodic_refetch_time = now_ts + 60.0
                        logging.debug("Scheduled periodic refetch in 60s (unknown time maps)")
                    else:
                        # Normal periodic refetch (5 minutes) for staleness prevention
                        self.periodic_refetch_time = now_ts + 300.0
                        logging.debug("Scheduled periodic refetch in 300s (staleness prevention)")
                # If periodic_refetch_time is already set and this wasn't a periodic fetch,
                # it will be recalculated on the next should_fetch call
            
            # Handle live time expiration locally (no fetch needed)
            expired_live_maps = []
            for mn in list(self.state.live_until_by_map.keys()):
                if self.state.live_until_by_map[mn] <= now_ts:
                    expired_live_maps.append(mn)
            
            # Remove expired live maps locally
            for mn in expired_live_maps:
                del self.state.live_until_by_map[mn]
                self.state.live_servers_by_map.pop(mn, None)
                self.live_map_resync_times.pop(mn, None)
                self.state.notified_live.discard(mn)  # Clear notification so it can notify again if it goes live
                logging.debug("Map #%s live time expired locally, removed from live state", mn)
            
            # Build live summary from local state only
            all_live_maps = set()
            for mn in self.watched:
                if mn in self.state.live_until_by_map and self.state.live_until_by_map[mn] > now_ts:
                    all_live_maps.add(mn)
                    # Notify if newly live (from ETA expiration)
                    if mn not in self.state.notified_live:
                        server = self.state.live_servers_by_map.get(mn, set())
                        server_str = ", ".join(sorted(server)) if server else ""
                        self.on_live_notification(mn, server_str)
                        self.state.mark_notified({mn})
                        logging.debug("KACKY MAP LIVE: #%s on %s", mn, server_str if server_str else "<unknown server>")
                        # Schedule resync 1 minute after going live
                        self.live_map_resync_times[mn] = now_ts + 60.0
                        logging.debug("Scheduled resync for map #%s in 60s", mn)
            
            # Format and send summary (use local state, not fetch data)
            live_summary, tracked_lines = self.format_summary([], False, all_live_maps if all_live_maps else None)
            self.on_summary_update(live_summary, tracked_lines)
            
            # Update status
            if not did_fetch:
                self.on_status_update("Idle (counting down ETAs)...")
            
            # Reset watchlist trigger
            self.watchlist_added = False
            
        except Exception as e:
            logging.exception("Error in poll cycle: %s", e)
            self.on_status_update(f"Error: {e}")
    
    def run(self) -> None:
        """
        Run the watcher in a continuous loop.
        Simplified: poll every second to handle countdown and fetch triggers.
        """
        while True:
            try:
                self.poll_once()
                
                # Sleep 1 second - poll_once handles countdown internally
                time.sleep(1.0)
            except KeyboardInterrupt:
                logging.debug("Exiting...")
                break
            except Exception as e:
                logging.exception("Unexpected error: %s", e)
                time.sleep(1)

