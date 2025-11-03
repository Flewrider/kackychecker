"""
CLI entry point for Kacky Watcher.
Maintains backwards compatibility with original script.
"""
import sys
import logging
from typing import List, Tuple

from config import load_config, setup_logging
from watcher_core import KackyWatcher


def format_cli_output(live_maps: List[int], tracked_lines: List[Tuple[int, str]], watcher: KackyWatcher) -> None:
    """
    Format and print CLI output.
    
    Args:
        live_maps: List of live map numbers
        tracked_lines: List of (eta_seconds, line_text) tuples
        watcher: Watcher instance for accessing state
    """
    import time
    
    print("\n========================================")
    
    # Format live section
    if live_maps:
        print("Live:")
        now_ts = time.time()
        for mn in live_maps:
            servers = sorted(watcher.state.live_servers_by_map.get(mn, set()))
            # Calculate remaining time
            remaining_sec = 0
            if mn in watcher.state.live_until_by_map:
                remaining_sec = max(0, int(watcher.state.live_until_by_map[mn] - now_ts))
            remaining_str = f" ({remaining_sec//60}:{remaining_sec%60:02d} remaining)" if remaining_sec > 0 else ""
            if servers:
                print(f"- {mn} on {', '.join(servers)}{remaining_str}")
            else:
                print(f"- {mn}{remaining_str}")
    else:
        print("Live:\n(none)")
    
    print("Tracked:")
    # Sort by ETA seconds (unknowns last)
    if tracked_lines:
        for _, line in sorted(tracked_lines, key=lambda x: x[0]):
            print(line)
    else:
        print("(none)")


def main() -> None:
    """Main CLI entry point."""
    cfg = load_config()
    setup_logging(cfg["LOG_LEVEL"])
    
    def on_live_notification(map_number: int, server: str) -> None:
        """Handle live map notification for CLI."""
        if server:
            print(f"KACKY MAP LIVE: #{map_number} on {server}")
        else:
            print(f"KACKY MAP LIVE: #{map_number}")
    
    def on_summary_update(live_maps: List[int], tracked_lines: List[Tuple[int, str]]) -> None:
        """Handle summary update for CLI."""
        # We'll format this in the watcher callback
        pass
    
    watcher = KackyWatcher(
        config=cfg,
        on_status_update=lambda msg: logging.debug("Status: %s", msg),
        on_live_notification=on_live_notification,
        on_summary_update=lambda live, tracked: format_cli_output(live, tracked, watcher),
    )
    
    # Override summary callback to include watcher reference
    def summary_callback(live_maps: List[int], tracked_lines: List[Tuple[int, str]]) -> None:
        format_cli_output(live_maps, tracked_lines, watcher)
        sleep_sec = max(1, cfg["WATCHLIST_REFRESH_SECONDS"])
        print(f"Next check in ~{sleep_sec}s")
    
    watcher.on_summary_update = summary_callback
    
    try:
        watcher.run()
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    # When executed via `python kacky_watcher.py`
    main()
