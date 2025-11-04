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
        
        Args:
            now_ts: Current timestamp
            
        Returns:
            Tuple of (should_fetch: bool, fetch_reason: str | None, triggering_maps: List)
        """
        # Check if any live maps are expiring very soon (within 10 seconds)
        # Use a tight threshold to avoid excessive fetching
        # Only check tracked maps
        expiring_live = self.state.has_expiring_live_windows(
            now_ts,
            threshold_sec=10,  # Only fetch when very close to expiry
            margin_sec=0,
            watched=self.watched  # Only check tracked maps
        )
        
        # Determine nearest ETA
        threshold_sec = self.config["ETA_FETCH_THRESHOLD_SECONDS"]
        nearest_eta, triggering_maps = self.state.get_nearest_eta(self.watched, threshold_sec, now_ts)
        # Convert to list of tuples for consistency
        
        fetch_reason = None
        if not self.state.eta_seconds_by_map:
            fetch_reason = "initial"
        elif self.watchlist_added:
            fetch_reason = "watchlist_added"
        elif expiring_live:
            fetch_reason = "live_window_expiring"
        elif nearest_eta <= threshold_sec:
            fetch_reason = "eta_threshold"
        
        should_fetch = fetch_reason is not None
        
        logging.debug(
            "Fetch decision: nearest_eta=%ss, threshold=%ss, watchlist_added=%s, should_fetch=%s (%s)",
            nearest_eta,
            threshold_sec,
            self.watchlist_added,
            should_fetch,
            fetch_reason,
        )
        
        return should_fetch, fetch_reason, triggering_maps
    
    def calculate_next_fetch_time(self, now_ts: float) -> float:
        """
        Calculate how many seconds until the next fetch is needed.
        
        Args:
            now_ts: Current timestamp
            
        Returns:
            Seconds until next fetch (0 if immediate fetch needed, max 300 seconds)
        """
        # If watchlist was added, fetch immediately
        if self.watchlist_added:
            return 0.0
        
        # Calculate time until next live window expires (only for tracked maps)
        next_live_expiry = self.state.get_next_live_window_expiry(now_ts, watched=self.watched)
        time_until_live_expiry = None
        if next_live_expiry:
            time_until_live_expiry = max(0.0, next_live_expiry - now_ts)
            # Only fetch when very close to expiry (within 10 seconds) to avoid continuous fetching
            # This allows the live window to persist naturally without constant refetches
            if time_until_live_expiry <= 10.0:
                return 0.0  # Fetch immediately if expiring very soon (within 10s)
            # Otherwise, return time until we need to fetch (when within 10s of expiry)
            # This prevents fetching too early - wait until 10s before expiry
            return max(1.0, time_until_live_expiry - 10.0)
        
        # Calculate time until next ETA expires
        next_eta_sec = self.state.get_next_eta_expiry(self.watched, now_ts)
        time_until_eta_expiry = None
        if next_eta_sec is not None:
            time_until_eta_expiry = float(next_eta_sec)
            # If ETA is within threshold, fetch immediately
            if time_until_eta_expiry <= self.config["ETA_FETCH_THRESHOLD_SECONDS"]:
                return 0.0
        
        # If no state and no watched maps, fetch immediately (initial state)
        # But if there are watched maps but no ETAs yet, wait a reasonable time before refetching
        if not self.state.eta_seconds_by_map and not self.state.live_until_by_map:
            if not self.watched:
                # No watched maps at all - no need to fetch
                return 300.0
            # Have watched maps but no ETAs - wait a bit before refetching (e.g., 30 seconds)
            # This prevents continuous fetching when a new map is added but not in schedule yet
            return 30.0
        
        # Find minimum time until next event
        candidates = []
        if time_until_live_expiry is not None:
            candidates.append(time_until_live_expiry)
        if time_until_eta_expiry is not None:
            candidates.append(time_until_eta_expiry)
        
        if not candidates:
            # No events scheduled, use a reasonable default (5 minutes)
            return 300.0
        
        # Return minimum time, capped at 5 minutes
        return min(min(candidates), 300.0)
    
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
            live_now: Set of live maps from update_from_fetch (already cooldown-filtered)
            
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
        # Use live_now passed from update_from_fetch (already cooldown-filtered)
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
        
        Args:
            force_fetch: If True, force a fetch regardless of should_fetch logic
        """
        try:
            logging.debug("Starting poll cycle…")
            
            # Reload map status if needed
            self.reload_status()
            
            # Decide if we should fetch
            now_ts = time.time()
            if force_fetch:
                should_fetch = True
                fetch_reason = "forced"
                triggering_maps = []
            else:
                should_fetch, fetch_reason, triggering_maps = self.should_fetch(now_ts)
            
            rows: List[Dict[str, str]] = []
            did_fetch = False
            
            if should_fetch:
                # Prevent rapid refetches - enforce minimum time between fetches (except for immediate triggers)
                min_fetch_interval = 2.0  # Minimum 2 seconds between fetches
                if now_ts - self.last_fetch_time < min_fetch_interval:
                    # Skip fetch if too soon (unless it's a critical reason or forced)
                    if fetch_reason not in ("watchlist_added", "initial", "forced"):
                        should_fetch = False
                        logging.debug("Skipping fetch (too soon after last fetch: %.1fs)", now_ts - self.last_fetch_time)
                
                if should_fetch:
                    # Log fetch reason
                    if fetch_reason == "initial":
                        logging.debug("Fetching schedule (reason: initial state)")
                        self.on_status_update("Fetching schedule (initial state)...")
                    elif fetch_reason == "watchlist_added":
                        logging.debug("Fetching schedule (reason: new map added to watchlist)")
                        self.on_status_update("Fetching schedule (new map added)...")
                    elif fetch_reason == "live_window_expiring":
                        logging.debug("Fetching schedule (reason: live map window expiring soon)")
                        self.on_status_update("Fetching schedule (live window expiring)...")
                    elif fetch_reason == "eta_threshold":
                        threshold_sec = self.config["ETA_FETCH_THRESHOLD_SECONDS"]
                        if triggering_maps:
                            maps_str = ", ".join([
                                f"#{mn} ({sec//60}:{sec%60:02d} on {srv})" if srv else f"#{mn} ({sec//60}:{sec%60:02d})"
                                for mn, sec, srv in sorted(triggering_maps, key=lambda x: x[1])
                            ])
                            logging.debug("Fetching schedule (reason: nearest tracked ETA ≤ %ss) - triggered by: %s", threshold_sec, maps_str)
                            self.on_status_update(f"Fetching schedule (ETA threshold: {maps_str})...")
                        else:
                            logging.debug("Fetching schedule (reason: nearest tracked ETA ≤ %ss)", threshold_sec)
                            self.on_status_update(f"Fetching schedule (ETA threshold ≤ {threshold_sec}s)...")
                    
                    # Call fetch_schedule with error handling for all fetch reasons
                    logging.debug("About to call fetch_schedule()...")
                    try:
                        rows = self.fetch_schedule()
                        logging.debug("fetch_schedule() returned with %d rows", len(rows))
                        did_fetch = True
                        self.last_fetch_time = now_ts
                    except Exception as e:
                        logging.error("Exception in fetch_schedule(): %s", e, exc_info=True)
                        rows = []
                        did_fetch = True
                        self.last_fetch_time = now_ts
                        
                        # Track successful fetches (rows > 0 means we got data)
                        if rows:
                            self.last_successful_fetch_time = now_ts
                            self.consecutive_fetch_failures = 0
                        else:
                            self.consecutive_fetch_failures += 1
                            if self.consecutive_fetch_failures >= 2:
                                # After 2 consecutive failures, show warning
                                time_since_success = now_ts - self.last_successful_fetch_time if self.last_successful_fetch_time > 0 else float('inf')
                                if time_since_success > 60:  # More than 1 minute since last success
                                    self.on_status_update(f"⚠️ Website unreachable or returned no data (last success: {int(time_since_success)}s ago)")
                                else:
                                    self.on_status_update("⚠️ Website unreachable or returned no data")
            else:
                # No fetch this cycle: don't countdown here
                # The GUI timer handles countdown for smooth display in GUI mode
                # For CLI mode, countdown happens in the sleep loop
                # Check if any watched map's ETA has hit 0 or gone negative (should be live now)
                expired_etas = []
                for mn in self.watched:
                    # Check single ETA
                    if mn in self.state.eta_seconds_by_map and self.state.eta_seconds_by_map[mn] <= 0:
                        # Only trigger if not already in live window
                        if mn not in self.state.live_until_by_map or self.state.live_until_by_map[mn] <= now_ts:
                            # Mark as recently finished if ETA is 0 (5 minute cooldown)
                            if self.state.eta_seconds_by_map[mn] == 0:
                                self.state.recently_finished_by_map[mn] = now_ts + 300
                                logging.debug("Map #%s ETA expired at 0:00, starting 5-minute cooldown", mn)
                            expired_etas.append(mn)
                    # Check upcoming servers
                    if mn in self.state.upcoming_by_map:
                        for srv, sec in self.state.upcoming_by_map[mn]:
                            if sec <= 0:
                                # Only trigger if not already in live window
                                if mn not in self.state.live_until_by_map or self.state.live_until_by_map[mn] <= now_ts:
                                    # Mark as recently finished if ETA is 0
                                    if sec == 0:
                                        self.state.recently_finished_by_map[mn] = now_ts + 300
                                        logging.debug("Map #%s ETA expired at 0:00 on server %s, starting 5-minute cooldown", mn, srv)
                                    if mn not in expired_etas:
                                        expired_etas.append(mn)
                                    break
                
                if expired_etas:
                    # ETA has expired, fetch immediately to catch map going live
                    # Check if enough time has passed since last fetch
                    if now_ts - self.last_fetch_time >= 2.0:
                        logging.debug("Fetching schedule (reason: ETA expired for map(s): %s)", sorted(expired_etas))
                        self.on_status_update(f"Fetching schedule (ETA expired: {', '.join(map(str, sorted(expired_etas)))})...")
                        logging.debug("About to call fetch_schedule() for expired ETA...")
                        try:
                            rows = self.fetch_schedule()
                            logging.debug("fetch_schedule() returned with %d rows", len(rows))
                            did_fetch = True
                            self.last_fetch_time = now_ts
                            
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
                            logging.error("Exception in fetch_schedule() for expired ETA: %s", e, exc_info=True)
                            rows = []
                            did_fetch = True
                            self.last_fetch_time = now_ts
                    else:
                        logging.debug("Skipping fetch for expired ETA (too soon after last fetch)")
                else:
                    # Check if we have stale data (all ETAs are 0 and no recent successful fetch)
                    if self.last_successful_fetch_time > 0:
                        time_since_success = now_ts - self.last_successful_fetch_time
                        # Check if all watched maps have ETA 0 (stale data)
                        all_etas_zero = True
                        for mn in self.watched:
                            if mn in self.state.eta_seconds_by_map and self.state.eta_seconds_by_map[mn] > 0:
                                all_etas_zero = False
                                break
                            if mn in self.state.upcoming_by_map:
                                for s, sec in self.state.upcoming_by_map[mn]:
                                    if sec > 0:
                                        all_etas_zero = False
                                        break
                        
                        if all_etas_zero and time_since_success > 120:
                            # All ETAs are 0 and data is stale
                            self.on_status_update(f"⚠️ Data may be stale - all ETAs at 0:00 (last fetch: {int(time_since_success)}s ago)")
                        else:
                            self.on_status_update("Idle (counting down ETAs)...")
                    else:
                        self.on_status_update("Idle (counting down ETAs)...")
            
            # Update state and get live maps
            if did_fetch:
                live_now = self.state.update_from_fetch(rows, self.watched)
                
                # Notify for newly live maps
                newly_live = self.state.get_newly_live(self.watched, live_now)
                for mn in sorted(newly_live):
                    server = next((r.get("server") for r in rows if r.get("map_number") == str(mn) and r.get("server")), "")
                    self.on_live_notification(mn, server)
                    logging.debug("KACKY MAP LIVE: #%s on %s", mn, server if server else "<unknown server>")
                self.state.mark_notified(newly_live)
                
                # Clear notifications for maps no longer live
                no_longer_live = self.state.notified_live - live_now
                if no_longer_live:
                    for mn in sorted(no_longer_live):
                        logging.debug("Map #%s no longer live", mn)
                    self.state.clear_notifications_for(no_longer_live)
            else:
                live_now = set()
            
            # Format and send summary (pass live_now so it uses the cooldown-filtered version)
            live_summary, tracked_lines = self.format_summary(rows, did_fetch, live_now)
            self.on_summary_update(live_summary, tracked_lines)
            
            # Reset watchlist trigger
            self.watchlist_added = False
            
        except Exception as e:
            logging.exception("Error in poll cycle: %s", e)
            self.on_status_update(f"Error: {e}")
    
    def run(self) -> None:
        """
        Run the watcher in a continuous loop.
        """
        while True:
            try:
                self.poll_once()
                
                # Calculate next fetch time dynamically
                next_fetch_sec = self.calculate_next_fetch_time(time.time())
                if next_fetch_sec > 0:
                    # Countdown ETAs during sleep
                    sleep_interval = 1.0  # Check every second
                    slept = 0.0
                    while slept < next_fetch_sec:
                        time.sleep(sleep_interval)
                        slept += sleep_interval
                        # Countdown ETAs by the sleep interval
                        self.state.countdown_etas(int(sleep_interval))
                else:
                    # Immediate fetch needed, don't sleep
                    pass
            except KeyboardInterrupt:
                logging.debug("Exiting...")
                break
            except Exception as e:
                logging.exception("Unexpected error: %s", e)
                time.sleep(1)

