import os
import re
import sys
import time
import logging
from typing import Dict, List, Set

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


SCHEDULE_URL = "https://kacky.gg/schedule"


def load_config() -> Dict[str, str]:
    load_dotenv()  # loads from .env in cwd if present
    check_interval = int(os.getenv("CHECK_INTERVAL_SECONDS", "20"))
    request_timeout = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "10"))
    user_agent = os.getenv("USER_AGENT", "KackyWatcher/1.0 (+https://kacky.gg/schedule)")
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    enable_browser = os.getenv("ENABLE_BROWSER", "0") in ("1", "true", "TRUE", "yes", "on")
    watchlist_refresh = int(os.getenv("WATCHLIST_REFRESH_SECONDS", "20"))
    eta_margin = int(os.getenv("ETA_MARGIN_SECONDS", "2"))
    eta_fetch_threshold = int(os.getenv("ETA_FETCH_THRESHOLD_SECONDS", "60"))
    live_duration_seconds = int(os.getenv("LIVE_DURATION_SECONDS", "600"))
    return {
        "CHECK_INTERVAL_SECONDS": check_interval,
        "REQUEST_TIMEOUT_SECONDS": request_timeout,
        "USER_AGENT": user_agent,
        "LOG_LEVEL": log_level,
        "ENABLE_BROWSER": enable_browser,
        "WATCHLIST_REFRESH_SECONDS": watchlist_refresh,
        "ETA_MARGIN_SECONDS": eta_margin,
        "ETA_FETCH_THRESHOLD_SECONDS": eta_fetch_threshold,
        "LIVE_DURATION_SECONDS": live_duration_seconds,
    }


def setup_logging(level_name: str) -> None:
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def load_watchlist(path: str = "watchlist.txt") -> Set[int]:
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
                # allow formats like "379 - anything" by extracting leading number
                m = re.match(r"\s*(\d+)", line)
                if m:
                    watched.add(int(m.group(1)))
    return watched


def fetch_schedule_html(user_agent: str | None = None, timeout: int = 10) -> str:
    headers = {"User-Agent": user_agent or "KackyWatcher/1.0 (+https://kacky.gg/schedule)"}
    resp = requests.get(SCHEDULE_URL, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def fetch_schedule_html_browser(timeout: int = 20, user_agent: str | None = None) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        logging.error("Playwright not available: %s", e)
        raise

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(user_agent=user_agent or "KackyWatcher/1.0 (+https://kacky.gg/schedule)")
            page = context.new_page()
            page.set_default_timeout(timeout * 1000)
            page.goto(SCHEDULE_URL, wait_until="domcontentloaded")
            # Wait briefly for dynamic content; look for either LIVE badge or Server label or the map title pattern
            try:
                page.wait_for_selector(r"text=/LIVE|Server \d+/", timeout=timeout * 1000)
            except Exception:
                pass
            html = page.content()
            return html
        finally:
            browser.close()


def parse_live_maps(html: str) -> List[Dict[str, str]]:
    """
    Returns a list of dicts with keys: map_number (str), server (optional), is_live (bool)
    Only rows parsed; callers can filter is_live.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict[str, str]] = []

    # Heuristic: row containers usually have multiple utility classes like rounded-lg, px-3, py-2 and layout classes
    def has_row_like_classes(el) -> bool:
        cls = el.get("class") or []
        cls_set = set(cls)
        return (
            ("rounded-lg" in cls_set or "rounded-md" in cls_set)
            and ("px-3" in cls_set or "px-2" in cls_set)
            and ("justify-between" in cls_set)
        )

    candidates = [d for d in soup.find_all("div") if has_row_like_classes(d)]
    if not candidates:
        # broader fallback: any div that contains a Server label or LIVE badge
        for d in soup.find_all("div"):
            txt = d.get_text(" ", strip=True)
            if ("Server " in txt) or ("LIVE" in txt.upper()):
                candidates.append(d)

    seen_keys: Set[str] = set()
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
            # try direct row text too
            t = row.get_text(" ", strip=True)
            m = re.match(r"^(\d+)\s*-\s*", t)
            if m:
                map_number = m.group(1)
        if not map_number:
            continue

        # Determine LIVE state anywhere within this row
        is_live = False
        server_label = ""
        eta_text = ""
        for d in row.find_all(["div", "span"]):
            t = d.get_text(" ", strip=True)
            if not server_label and t.startswith("Server "):
                server_label = t
            if "LIVE" in t.upper():
                is_live = True
            # pick up ETA like 0:47, 10:20, 1:03, 30:47, etc.
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

        rows.append({"map_number": map_number, "server": server_label, "is_live": is_live, "eta": eta_text})

    return rows


def main() -> None:
    cfg = load_config()
    setup_logging(cfg["LOG_LEVEL"])  # type: ignore[arg-type]

    watched = load_watchlist()
    watchlist_path = "watchlist.txt"
    last_watchlist_mtime = os.path.getmtime(watchlist_path) if os.path.exists(watchlist_path) else 0.0
    last_watchlist_check = 0.0
    if not watched:
        logging.warning("watchlist.txt is empty or missing. Add map numbers to watch.")

    logging.info("Watching %d map(s): %s", len(watched), ", ".join(map(str, sorted(watched))) if watched else "<none>")
    logging.info("Polling %s every %ss", SCHEDULE_URL, cfg["CHECK_INTERVAL_SECONDS"])  # type: ignore[index]

    # Remember which watched maps are currently live to avoid repeat notifications
    notified_live: Set[int] = set()
    # Predicted ETAs and servers between fetches
    eta_seconds_by_map: Dict[int, int] = {}
    server_by_map: Dict[int, str] = {}
    # Persist live state for a period (maps are ~10 minutes live)
    live_until_by_map: Dict[int, float] = {}
    live_servers_by_map: Dict[int, Set[str]] = {}
    # Track multiple upcoming per map (server, seconds)
    upcoming_by_map: Dict[int, List[tuple[str, int]]] = {}

    watchlist_added = False
    while True:
        try:
            logging.debug("Starting poll cycle…")
            # Periodically reload watchlist if file changed
            now = time.time()
            if now - last_watchlist_check >= int(cfg["WATCHLIST_REFRESH_SECONDS"]):  # type: ignore[index]
                last_watchlist_check = now
                try:
                    mtime = os.path.getmtime(watchlist_path) if os.path.exists(watchlist_path) else 0.0
                    if mtime and mtime != last_watchlist_mtime:
                        prev_watched = set(watched)
                        watched = load_watchlist(watchlist_path)
                        last_watchlist_mtime = mtime
                        logging.info("Reloaded watchlist: %s", sorted(watched))
                        added = watched - prev_watched
                        if added:
                            logging.debug("New map(s) added: %s", sorted(added))
                            watchlist_added = True
                except Exception:
                    logging.debug("Could not stat/reload watchlist.")

            # Decide if we should fetch: initial run, new maps, ETA threshold, or live window expiring
            now_ts = time.time()
            # Check if any live maps are expiring soon (within threshold + margin)
            expiring_live = False
            for mn, until_ts in list(live_until_by_map.items()):
                if until_ts <= now_ts + int(cfg["ETA_FETCH_THRESHOLD_SECONDS"]) + 5:  # type: ignore[index]
                    expiring_live = True
                    break
            # Determine nearest ETA among positive values only, excluding maps currently in live window
            nearest_eta = 10**9
            threshold_sec = int(cfg["ETA_FETCH_THRESHOLD_SECONDS"])  # type: ignore[index]
            triggering_maps: List[tuple[int, int, str]] = []  # (map_num, eta_sec, server)
            try:
                candidates = []
                # First, check non-live maps (only watched ones)
                for mn, sec in eta_seconds_by_map.items():
                    if sec > 0 and mn in watched:  # Only consider watched maps
                        # Skip if this map is currently live
                        if mn not in live_until_by_map or live_until_by_map[mn] <= now_ts:
                            candidates.append(sec)
                            if sec <= threshold_sec:
                                triggering_maps.append((mn, sec, server_by_map.get(mn, "")))
                # Also check upcoming servers for live maps (if they're below threshold and watched)
                for mn, items in upcoming_by_map.items():
                    if mn in watched and mn in live_until_by_map and live_until_by_map[mn] > now_ts:
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
            fetch_reason = None
            if not eta_seconds_by_map:
                fetch_reason = "initial"
            elif watchlist_added:
                fetch_reason = "watchlist_added"
            elif expiring_live:
                fetch_reason = "live_window_expiring"
            elif nearest_eta <= int(cfg["ETA_FETCH_THRESHOLD_SECONDS"]):  # type: ignore[index]
                fetch_reason = "eta_threshold"
            should_fetch = fetch_reason is not None
            logging.debug(
                "Fetch decision: nearest_eta=%ss, threshold=%ss, watchlist_added=%s, should_fetch=%s (%s)",
                nearest_eta,
                int(cfg["ETA_FETCH_THRESHOLD_SECONDS"]),  # type: ignore[index]
                watchlist_added,
                should_fetch,
                fetch_reason,
            )
            rows: List[Dict[str, str]] = []
            did_fetch = False
            if should_fetch:
                # Log why we're calling the server
                if fetch_reason == "initial":
                    logging.info("Fetching schedule (reason: initial state)")
                elif fetch_reason == "watchlist_added":
                    logging.info("Fetching schedule (reason: new map added to watchlist)")
                elif fetch_reason == "live_window_expiring":
                    logging.info("Fetching schedule (reason: live map window expiring soon)")
                elif fetch_reason == "eta_threshold":
                    if triggering_maps:
                        maps_str = ", ".join([f"#{mn} ({sec//60}:{sec%60:02d} on {srv})" if srv else f"#{mn} ({sec//60}:{sec%60:02d})" for mn, sec, srv in sorted(triggering_maps, key=lambda x: x[1])])
                        logging.info("Fetching schedule (reason: nearest tracked ETA ≤ %ss) - triggered by: %s", threshold_sec, maps_str)
                    else:
                        logging.info("Fetching schedule (reason: nearest tracked ETA ≤ %ss)", threshold_sec)
                html = fetch_schedule_html(cfg["USER_AGENT"], cfg["REQUEST_TIMEOUT_SECONDS"])  # type: ignore[index]
                did_fetch = True
                logging.debug("Fetched %d chars of HTML", len(html))
                rows = parse_live_maps(html)
                logging.debug("Parsed %d schedule rows", len(rows))
                if logging.getLogger().isEnabledFor(logging.DEBUG):
                    for i, r in enumerate(rows[:50]):  # cap to avoid flooding
                        logging.debug("Row %02d → map=%s server='%s' live=%s", i + 1, r.get("map_number"), r.get("server", ""), r.get("is_live"))
                if not rows and cfg.get("ENABLE_BROWSER"):
                    logging.debug("No rows via plain HTTP; trying headless browser (Playwright)…")
                    try:
                        html = fetch_schedule_html_browser(timeout=int(cfg["REQUEST_TIMEOUT_SECONDS"]) * 2, user_agent=cfg["USER_AGENT"])  # type: ignore[index]
                        logging.debug("[browser] Fetched %d chars of HTML", len(html))
                        rows = parse_live_maps(html)
                        logging.debug("[browser] Parsed %d schedule rows", len(rows))
                    except Exception as e:
                        logging.error("Browser fetch failed: %s", e)

                if not rows:
                    logging.warning("Parsed 0 rows — site structure may have changed or is client-rendered.")

            # Aggregate live status by map number and refresh caches if fetched
            live_now: Set[int] = set()
            if did_fetch:
                eta_seconds_by_map.clear()
                server_by_map.clear()
                upcoming_by_map.clear()
                for r in rows:
                    try:
                        mn = int(r.get("map_number", "0"))
                    except ValueError:
                        continue
                    srv = r.get("server", "") or ""
                    if r.get("is_live"):
                        live_now.add(mn)
                        # Only set live window if newly live (not already tracked)
                        if mn not in live_until_by_map:
                            live_until_by_map[mn] = time.time() + int(cfg["LIVE_DURATION_SECONDS"])  # type: ignore[index]
                            logging.debug("Set live window for map #%s until %s", mn, live_until_by_map[mn])
                        live_servers_by_map.setdefault(mn, set()).add(srv) if srv else None
                        # Remove from ETA tracking since it's live on this server
                        # But keep upcoming entries for other servers
                        eta_seconds_by_map.pop(mn, None)
                        server_by_map.pop(mn, None)
                        # Only remove upcoming entries for the server where it's live
                        if mn in upcoming_by_map and srv:
                            upcoming_by_map[mn] = [(s, t) for s, t in upcoming_by_map[mn] if s != srv]
                            if not upcoming_by_map[mn]:
                                del upcoming_by_map[mn]
                    else:
                        eta = r.get("eta", "") or ""
                        if eta:
                            m = re.match(r"^(\d{1,2}):(\d{2})$", eta)
                            if m:
                                sec = int(m.group(1)) * 60 + int(m.group(2))
                                # store single-earliest summary
                                if (mn not in eta_seconds_by_map) or (sec < eta_seconds_by_map[mn]):
                                    eta_seconds_by_map[mn] = sec
                                    server_by_map[mn] = srv
                                # store per-server list
                                if srv:
                                    upcoming_by_map.setdefault(mn, [])
                                    # keep only earliest per server
                                    existing = {s: t for s, t in upcoming_by_map[mn]}
                                    if (srv not in existing) or (sec < existing[srv]):
                                        # rebuild list with updated server time
                                        existing[srv] = sec
                                        upcoming_by_map[mn] = sorted(existing.items(), key=lambda x: x[1])
            else:
                # No fetch this cycle: count down predictions by refresh interval
                dec = int(cfg["WATCHLIST_REFRESH_SECONDS"])  # type: ignore[index]
                for k in list(eta_seconds_by_map.keys()):
                    eta_seconds_by_map[k] = max(0, eta_seconds_by_map[k] - dec)
                for mn, items in list(upcoming_by_map.items()):
                    updated = [(s, max(0, t - dec)) for s, t in items]
                    upcoming_by_map[mn] = updated
                # live persistence handled via live_until_by_map timestamps

            logging.debug("Watched=%s", sorted(watched))
            logging.debug("Live now (fetched)=%s", sorted(live_now))
            logging.debug("Already notified=%s", sorted(notified_live))

            # Notify for watched maps that are newly live (only when we fetched)
            if did_fetch:
                newly_live = (watched & live_now) - notified_live
                for mn in sorted(newly_live):
                    server = next((r.get("server") for r in rows if r.get("map_number") == str(mn) and r.get("server")), "")
                    if server:
                        print(f"KACKY MAP LIVE: #{mn} on {server}")
                    else:
                        print(f"KACKY MAP LIVE: #{mn}")
                    notified_live.add(mn)

            if not newly_live:
                # Explain why nothing printed
                if not watched:
                    logging.debug("No output: watchlist is empty.")
                elif not (watched & live_now):
                    logging.debug("No output: none of the watched maps are live. (watched=%s, live_now=%s)", sorted(watched), sorted(live_now))
                else:
                    logging.debug("No output: watched map(s) are live but were already notified. newly_live=%s", sorted(newly_live))

            # Clear notifications (only when we fetched)
            if did_fetch:
                no_longer_live = notified_live - live_now
                if no_longer_live:
                    for mn in sorted(no_longer_live):
                        logging.debug("Map #%s no longer live", mn)
                    notified_live -= no_longer_live

            # --- Summary output separator ---
            print("\n========================================")
            # --- Summary output of live and upcoming ETAs for watched maps ---
            # Build earliest ETA per watched map when not live
            def eta_to_seconds(eta: str) -> int:
                m = re.match(r"^(\d{1,2}):(\d{2})$", eta)
                if not m:
                    return 10**9
                return int(m.group(1)) * 60 + int(m.group(2))

            earliest_eta_by_map: Dict[int, Dict[str, str]] = {}
            for r in rows:
                try:
                    mn = int(r.get("map_number", "0"))
                except ValueError:
                    continue
                if mn not in watched:
                    continue
                if r.get("is_live"):
                    continue
                eta = r.get("eta", "") or ""
                if not eta:
                    continue
                cur = earliest_eta_by_map.get(mn)
                if cur is None or eta_to_seconds(eta) < eta_to_seconds(cur.get("eta", "999:59")):
                    earliest_eta_by_map[mn] = {"eta": eta, "server": r.get("server", "")}

            # Determine live maps for summary: any fetched-live OR within persistence window
            now_ts = time.time()
            # Clean up expired live windows
            for mn in list(live_until_by_map.keys()):
                if live_until_by_map[mn] <= now_ts:
                    del live_until_by_map[mn]
                    live_servers_by_map.pop(mn, None)
            live_summary: List[int] = []
            for mn in sorted(watched):
                if mn in live_now or (mn in live_until_by_map and live_until_by_map[mn] > now_ts):
                    live_summary.append(mn)
            if live_summary:
                print("Live:")
                for mn in live_summary:
                    servers = sorted(live_servers_by_map.get(mn, set()))
                    # Calculate remaining time
                    remaining_sec = 0
                    if mn in live_until_by_map:
                        remaining_sec = max(0, int(live_until_by_map[mn] - now_ts))
                    remaining_str = f" ({remaining_sec//60}:{remaining_sec%60:02d} remaining)" if remaining_sec > 0 else ""
                    if servers:
                        print(f"- {mn} on {', '.join(servers)}{remaining_str}")
                    else:
                        print(f"- {mn}{remaining_str}")

            print("Tracked:")
            # Build sortable list of (eta_seconds, line_str) for non-live watched maps
            # Also include upcoming servers for live maps
            tracked_lines: List[tuple[int, str]] = []
            BIG = 10**9
            # First, add non-live maps
            for mn in sorted(set(watched) - set(live_summary)):
                eta_sec = BIG
                line = f"- {mn} will be live in unknown"

                info = earliest_eta_by_map.get(mn)
                if did_fetch and info:
                    # Prefer exact from fetched page
                    # Convert to seconds for sorting
                    m = re.match(r"^(\d{1,2}):(\d{2})$", info.get("eta", ""))
                    if m:
                        eta_sec = int(m.group(1)) * 60 + int(m.group(2))
                    if info.get("server"):
                        line = f"- {mn} will be live in {info['eta']} on {info['server']}"
                    else:
                        line = f"- {mn} will be live in {info['eta']}"
                else:
                    # Use predicted ETA if available (with per-server upcoming first)
                    if mn in upcoming_by_map and upcoming_by_map[mn]:
                        s, sec = upcoming_by_map[mn][0]
                        eta_sec = sec
                        if s:
                            line = f"- {mn} will be live in {sec//60}:{sec%60:02d} on {s}"
                        else:
                            line = f"- {mn} will be live in {sec//60}:{sec%60:02d}"
                    elif mn in eta_seconds_by_map:
                        sec = eta_seconds_by_map[mn]
                        eta_sec = sec
                        srv = server_by_map.get(mn, "")
                        if srv:
                            line = f"- {mn} will be live in {sec//60}:{sec%60:02d} on {srv}"
                        else:
                            line = f"- {mn} will be live in {sec//60}:{sec%60:02d}"

                tracked_lines.append((eta_sec, line))
            
            # Also add upcoming servers for live maps
            for mn in live_summary:
                if mn in upcoming_by_map and upcoming_by_map[mn]:
                    for s, sec in upcoming_by_map[mn]:
                        tracked_lines.append((sec, f"- {mn} will be live in {sec//60}:{sec%60:02d} on {s}"))

            # Sort by ETA seconds (unknowns last)
            for _, line in sorted(tracked_lines, key=lambda x: x[0]):
                print(line)

            # Sleep: only the watchlist refresh cadence; fetching is condition-based
            sleep_sec = int(cfg["WATCHLIST_REFRESH_SECONDS"])  # type: ignore[index]
            if sleep_sec < 1:
                sleep_sec = 1
            print(f"Next check in ~{sleep_sec}s")
            # Reset watchlist trigger after acting on it
            watchlist_added = False

        except KeyboardInterrupt:
            print("\nExiting...")
            sys.exit(0)
        except requests.HTTPError as e:
            logging.error("HTTP error: %s", e)
        except requests.RequestException as e:
            logging.error("Network error: %s", e)
        except Exception as e:
            logging.exception("Unexpected error: %s", e)

        time.sleep(int(cfg["WATCHLIST_REFRESH_SECONDS"]))  # type: ignore[index]


if __name__ == "__main__":  # pragma: no cover
    # When executed via `python kacky_watcher.py`
    main()


