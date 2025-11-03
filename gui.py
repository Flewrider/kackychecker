"""
GUI module for Kacky Watcher using tkinter.
Provides split-pane interface with map list (tracking/finished checkboxes) and live/tracked output.
"""
import logging
import threading
import time
from typing import List, Set, Tuple, Optional

import tkinter as tk
from tkinter import ttk, scrolledtext

from config import load_config, setup_logging
from watcher_core import KackyWatcher
from map_status_manager import save_map_status, get_tracking_maps, get_finished_maps


class KackyWatcherGUI:
    """
    Main GUI application for Kacky Watcher.
    """
    
    def __init__(self, root: tk.Tk):
        """
        Initialize GUI.
        
        Args:
            root: Tkinter root window
        """
        print("GUI __init__ started")
        self.root = root
        print("Setting window properties...")
        self.root.title("Kacky Watcher")
        self.root.geometry("1200x700")
        
        print("Loading config...")
        self.config = load_config()
        print("Setting up logging...")
        setup_logging(self.config["LOG_LEVEL"])
        print("Config and logging complete")
        
        # Map status file path
        self.status_file = "map_status.json"
        
        # Map range
        self.map_range_start = 375
        self.map_range_end = 450
        
        # Debounce timer for status saving
        self.save_timer: Optional[str] = None
        
        # Watcher thread
        self.watcher: Optional[KackyWatcher] = None
        self.watcher_thread: Optional[threading.Thread] = None
        self.running = False
        self.immediate_fetch_event = threading.Event()  # Signal to trigger immediate fetch
        self.transition_refetch_timers: dict[int, str] = {}  # Map number -> timer ID for transition refetches
        
        # Current state for display
        self.live_maps: List[int] = []
        self.tracked_lines: List[Tuple[int, str]] = []
        self.last_fetch_timestamp: float = 0.0  # Timestamp of last fetch for countdown calculation
        self.last_countdown_update: float = 0.0  # Timestamp of last countdown update
        self.countdown_timer_id: Optional[str] = None  # ID of countdown timer
        
        # Map checkbox variables and row widgets (map_number -> (tracking_var, finished_var, row_frame))
        self.tracking_vars: dict[int, tk.BooleanVar] = {}
        self.finished_vars: dict[int, tk.BooleanVar] = {}
        self.map_rows: dict[int, tk.Frame] = {}
        self.updating_checkboxes = False  # Flag to prevent recursive updates
        
        try:
            print("Setting up UI...")
            self.setup_ui()
            print("UI setup complete, loading map status...")
            self.load_map_status()
            print("Map status loaded, scheduling watcher start...")
            
            # Start watcher after a short delay to ensure GUI is fully rendered
            self.root.after(100, self.start_watcher)
            # Start countdown timer
            self.root.after(200, self.start_countdown_timer)
            print("GUI initialization complete")
        except Exception as e:
            import traceback
            print(f"Error initializing GUI: {e}")
            traceback.print_exc()
            raise
    
    def setup_ui(self) -> None:
        """Set up the user interface."""
        # Main container with split pane
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Left pane: Map list with checkboxes
        left_frame = ttk.Frame(main_paned)
        main_paned.add(left_frame, weight=1)
        
        # Header
        header_frame = ttk.Frame(left_frame)
        header_frame.pack(fill=tk.X, padx=5, pady=(5, 2))
        ttk.Label(header_frame, text="Maps", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        
        # Column headers - use grid for better alignment
        header_row = ttk.Frame(left_frame)
        header_row.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(header_row, text="Map", width=8, font=("Arial", 9, "bold")).grid(row=0, column=0, padx=2)
        ttk.Label(header_row, text="Tracking", width=10, font=("Arial", 9, "bold")).grid(row=0, column=1, padx=2)
        ttk.Label(header_row, text="Finished", width=10, font=("Arial", 9, "bold")).grid(row=0, column=2, padx=2)
        # Configure grid columns to not expand
        header_row.grid_columnconfigure(0, weight=0)
        header_row.grid_columnconfigure(1, weight=0)
        header_row.grid_columnconfigure(2, weight=0)
        
        # Scrollable frame for map list
        canvas_frame = ttk.Frame(left_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        canvas = tk.Canvas(canvas_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
        self.map_container = ttk.Frame(canvas)
        
        canvas_window = canvas.create_window((0, 0), window=self.map_container, anchor=tk.NW)
        
        def configure_scroll_region(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        def configure_canvas_width(event):
            canvas_width = event.width
            canvas.itemconfig(canvas_window, width=canvas_width)
        
        self.map_container.bind("<Configure>", configure_scroll_region)
        canvas.bind("<Configure>", configure_canvas_width)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Mouse wheel scrolling (Windows)
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
        # Bind mouse wheel to canvas_frame and all child widgets
        def bind_mousewheel(widget):
            widget.bind("<MouseWheel>", on_mousewheel)
            for child in widget.winfo_children():
                bind_mousewheel(child)
        
        # Bind to canvas_frame and propagate to all children
        canvas.bind("<MouseWheel>", on_mousewheel)
        canvas_frame.bind("<MouseWheel>", on_mousewheel)
        self.map_container.bind("<MouseWheel>", on_mousewheel)
        # Also bind to all existing and future children
        bind_mousewheel(self.map_container)
        
        # Store canvas reference
        self.map_canvas = canvas
        
        # Right pane: Output display
        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame, weight=1)
        
        ttk.Label(right_frame, text="Live & Tracked Maps", font=("Arial", 10, "bold")).pack(anchor=tk.W, padx=5, pady=(5, 2))
        
        self.output_text = scrolledtext.ScrolledText(
            right_frame,
            wrap=tk.WORD,
            font=("Consolas", 10),
            height=30,
            state=tk.DISABLED
        )
        self.output_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Status bar
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, padx=5, pady=(0, 5))
        
        self.status_label = ttk.Label(status_frame, text="Initializing...", relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.pack(fill=tk.X, padx=2, pady=2)
        
        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        print("UI components created")
    
    def populate_map_list(self) -> None:
        """Populate the map list with maps 375-450."""
        # Prevent recursive calls
        if hasattr(self, '_populating') and self._populating:
            return
        self._populating = True
        
        try:
            print(f"Populating map list ({self.map_range_start}-{self.map_range_end})...")
            # Clear existing rows but preserve checkbox variable values
            for widget in self.map_container.winfo_children():
                widget.destroy()
            
            self.map_rows.clear()
            # Preserve checkbox variable values before reading from file
            # This ensures UI state is preserved during repopulation
            preserved_tracking = {mn: var.get() for mn, var in self.tracking_vars.items()}
            preserved_finished = {mn: var.get() for mn, var in self.finished_vars.items()}
            
            # Get current status from file
            tracking_from_file = get_tracking_maps(self.status_file)
            finished_from_file = get_finished_maps(self.status_file)
            
            # Merge: use preserved values if available, otherwise use file values
            # This ensures checkbox states are preserved even if file hasn't been saved yet
            tracking = tracking_from_file.copy()
            tracking.update({mn for mn, val in preserved_tracking.items() if val})
            
            finished = finished_from_file.copy()
            finished.update({mn for mn, val in preserved_finished.items() if val})
            
            # Clear checkbox variables to rebuild them
            self.tracking_vars.clear()
            self.finished_vars.clear()
            
            # Separate finished and unfinished maps
            unfinished_maps = []
            finished_maps = []
            
            for map_num in range(self.map_range_start, self.map_range_end + 1):
                if map_num in finished:
                    finished_maps.append(map_num)
                else:
                    unfinished_maps.append(map_num)
            
            # Sort both lists
            unfinished_maps.sort()
            finished_maps.sort()
            
            print(f"Adding {len(unfinished_maps)} unfinished maps...")
            # Add unfinished maps first (normal color)
            for i, map_num in enumerate(unfinished_maps):
                if i % 20 == 0:
                    print(f"  Added {i}/{len(unfinished_maps)} unfinished maps...")
                self.add_map_row(map_num, map_num in tracking, map_num in finished)
            
            print(f"Adding {len(finished_maps)} finished maps...")
            # Add finished maps at bottom (green background)
            for map_num in finished_maps:
                self.add_map_row(map_num, map_num in tracking, map_num in finished, is_finished_flag=True)
            
            # Rebind mouse wheel to new widgets
            def bind_mousewheel(widget):
                widget.bind("<MouseWheel>", lambda e: self.map_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
                for child in widget.winfo_children():
                    bind_mousewheel(child)
            bind_mousewheel(self.map_container)
            
            print("Map list population complete")
        finally:
            self._populating = False
    
    def add_map_row(self, map_num: int, is_tracking: bool, is_finished: bool, is_finished_flag: bool = False) -> None:
        """
        Add a map row to the list.
        
        Args:
            map_num: Map number
            is_tracking: Whether map is being tracked
            is_finished: Whether map is finished
            is_finished_flag: Whether this is being added as a finished map (for styling)
        """
        # Create checkbox variables if not exists
        if map_num not in self.tracking_vars:
            var = tk.BooleanVar(value=is_tracking)
            self.tracking_vars[map_num] = var
        else:
            var = self.tracking_vars[map_num]
            # Update value - this won't trigger command since we set command after
            var.set(is_tracking)
        
        if map_num not in self.finished_vars:
            var_finished = tk.BooleanVar(value=is_finished)
            self.finished_vars[map_num] = var_finished
        else:
            var_finished = self.finished_vars[map_num]
            # Update value - this won't trigger command since we set command after
            var_finished.set(is_finished)
        
        # Use colored frame for finished maps, regular frame for others
        if is_finished_flag or is_finished:
            row_frame = tk.Frame(self.map_container, bg="#90EE90")  # Light green
            bg_color = "#90EE90"
        else:
            row_frame = ttk.Frame(self.map_container)
            bg_color = None
        
        # Use grid layout for consistent alignment regardless of window size
        row_frame.grid_columnconfigure(0, weight=0)
        row_frame.grid_columnconfigure(1, weight=0)
        row_frame.grid_columnconfigure(2, weight=0)
        
        # Map number label
        if bg_color:
            map_label = tk.Label(row_frame, text=str(map_num), width=8, anchor=tk.CENTER, bg=bg_color)
        else:
            map_label = ttk.Label(row_frame, text=str(map_num), width=8, anchor=tk.CENTER)
        map_label.grid(row=0, column=0, padx=2, sticky=tk.W)
        
        # Tracking checkbox - use grid for alignment
        tracking_cb = ttk.Checkbutton(row_frame, variable=self.tracking_vars[map_num])
        tracking_cb.grid(row=0, column=1, padx=2, sticky=tk.W)
        # Now set the command after the variable is set
        tracking_cb.configure(command=lambda mn=map_num: self.on_checkbox_change(mn, "tracking"))
        
        # Finished checkbox - use grid for alignment
        finished_cb = ttk.Checkbutton(row_frame, variable=self.finished_vars[map_num])
        finished_cb.grid(row=0, column=2, padx=2, sticky=tk.W)
        # Now set the command after the variable is set
        finished_cb.configure(command=lambda mn=map_num: self.on_checkbox_change(mn, "finished"))
        
        # Pack the row frame itself
        row_frame.pack(fill=tk.X, pady=1)
        
        self.map_rows[map_num] = row_frame
    
    def on_checkbox_change(self, map_num: int, checkbox_type: str) -> None:
        """
        Handle checkbox change.
        
        Args:
            map_num: Map number
            checkbox_type: "tracking" or "finished"
        """
        # Skip if we're updating checkboxes programmatically
        if self.updating_checkboxes:
            return
        
        # Cancel previous timer
        if self.save_timer:
            self.root.after_cancel(self.save_timer)
        
        # If finished checkbox was checked, save immediately and refresh the list to move it to bottom
        if checkbox_type == "finished":
            # Save immediately so repopulate can read the updated state
            self.save_map_status()
            # Schedule repopulation after a short delay to allow file write to complete
            self.root.after(100, self.populate_map_list)
        
        # Schedule save after 0.5 seconds of no changes
        self.save_timer = self.root.after(500, self.save_map_status)
        
        # Update watcher if tracking changed
        if checkbox_type == "tracking" and self.watcher:
            # Update watched set directly from checkbox states (don't wait for file save)
            new_tracking = set()
            for map_num, var in self.tracking_vars.items():
                if var.get():
                    new_tracking.add(map_num)
            
            # Only trigger fetch if this is actually a change (map added or removed)
            if new_tracking != self.watcher.watched:
                self.watcher.watched = new_tracking
                self.watcher.watchlist_added = True
                # Trigger immediate fetch
                self.immediate_fetch_event.set()
                # Force display refresh to show new map immediately (even if no ETA yet)
                self.root.after(50, self._refresh_display)
    
    def load_map_status(self) -> None:
        """Load map status from JSON and populate the list."""
        self.populate_map_list()
    
    def save_map_status(self) -> None:
        """Save map status to JSON file."""
        tracking = set()
        finished = set()
        
        for map_num, var in self.tracking_vars.items():
            if var.get():
                tracking.add(map_num)
        
        for map_num, var in self.finished_vars.items():
            if var.get():
                finished.add(map_num)
        
        try:
            save_map_status(tracking, finished, self.status_file)
            self.update_status("Map status saved")
        except Exception as e:
            self.update_status(f"Error saving map status: {e}")
    
    def update_status(self, message: str) -> None:
        """
        Update status bar.
        
        Args:
            message: Status message to display
        """
        timestamp = time.strftime("%H:%M:%S")
        self.status_label.config(text=f"[{timestamp}] {message}")
    
    def on_live_notification(self, map_number: int, server: str) -> None:
        """
        Handle live map notification.
        
        Args:
            map_number: Map number that went live
            server: Server name or empty string
        """
        # This will be called from watcher thread, so schedule GUI update
        self.root.after(0, lambda: self._show_live_notification(map_number, server))
    
    def _show_live_notification(self, map_number: int, server: str) -> None:
        """Show live notification in GUI (called on main thread)."""
        server_text = f" on {server}" if server else ""
        self.update_status(f"🎉 Map #{map_number} is LIVE{server_text}!")
        
        # Schedule a refetch after ~1 minute to handle map transition period
        # Cancel any existing timer for this map
        if map_number in self.transition_refetch_timers:
            self.root.after_cancel(self.transition_refetch_timers[map_number])
        
        # Schedule refetch after 80 seconds
        def transition_refetch():
            """Trigger fetch after map transition period."""
            if self.watcher and self.running:
                logging.info("Fetching schedule (reason: map transition period - map #%s went live ~1 min ago)", map_number)
                self.update_status(f"Refetching after map #{map_number} transition...")
                self.immediate_fetch_event.set()
            # Clean up timer reference
            if map_number in self.transition_refetch_timers:
                del self.transition_refetch_timers[map_number]
        
        timer_id = self.root.after(80000, transition_refetch)
        self.transition_refetch_timers[map_number] = timer_id
    
    def on_summary_update(self, live_maps: List[int], tracked_lines: List[Tuple[int, str]]) -> None:
        """
        Handle summary update from watcher.
        
        Args:
            live_maps: List of live map numbers
            tracked_lines: List of (eta_seconds, line_text) tuples
        """
        # This will be called from watcher thread, so schedule GUI update
        self.root.after(0, lambda: self._update_output(live_maps, tracked_lines))
    
    def _update_output(self, live_maps: List[int], tracked_lines: List[Tuple[int, str]]) -> None:
        """Update output display (called on main thread)."""
        self.live_maps = live_maps
        self.tracked_lines = tracked_lines
        # Force refresh to ensure new maps appear immediately
        self._refresh_display()
    
    def _refresh_display(self) -> None:
        """Refresh the display with current countdown values."""
        now_ts = time.time()
        
        self.output_text.config(state=tk.NORMAL)
        self.output_text.delete("1.0", tk.END)
        
        # Format live section
        if self.watcher and hasattr(self.watcher, 'state'):
            # Get watched maps from checkbox states (source of truth)
            watched_for_live = set()
            if hasattr(self, 'tracking_vars'):
                for map_num, var in self.tracking_vars.items():
                    if var.get():
                        watched_for_live.add(map_num)
            else:
                watched_for_live = self.watcher.watched if self.watcher else set()
            
            live_summary = self.watcher.state.get_live_summary(
                watched_for_live,
                set(self.live_maps),
                now_ts
            )
            
            if live_summary:
                self.output_text.insert(tk.END, "Live:\n", "live_header")
                for mn in live_summary:
                    # Get servers and remaining time from watcher state
                    servers = sorted(self.watcher.state.live_servers_by_map.get(mn, set()))
                    remaining_sec = 0
                    if mn in self.watcher.state.live_until_by_map:
                        remaining_sec = max(0, int(self.watcher.state.live_until_by_map[mn] - now_ts))
                    
                    remaining_str = f" ({remaining_sec//60}:{remaining_sec%60:02d} remaining)" if remaining_sec > 0 else ""
                    if servers:
                        self.output_text.insert(tk.END, f"- {mn} on {', '.join(servers)}{remaining_str}\n")
                    else:
                        self.output_text.insert(tk.END, f"- {mn}{remaining_str}\n")
                self.output_text.insert(tk.END, "\n")
            else:
                self.output_text.insert(tk.END, "Live:\n(none)\n\n")
        elif self.live_maps:
            self.output_text.insert(tk.END, "Live:\n", "live_header")
            for mn in self.live_maps:
                self.output_text.insert(tk.END, f"- {mn}\n")
            self.output_text.insert(tk.END, "\n")
        else:
            self.output_text.insert(tk.END, "Live:\n(none)\n\n")
        
        # Format tracked section
        self.output_text.insert(tk.END, "Tracked:\n", "tracked_header")
        if self.watcher and hasattr(self.watcher, 'state'):
            tracked_display_lines = []
            BIG = 10**9
            
            # Get watched maps from checkbox states (source of truth) or watcher as fallback
            watched = set()
            if hasattr(self, 'tracking_vars'):
                # Use checkbox states as source of truth
                for map_num, var in self.tracking_vars.items():
                    if var.get():
                        watched.add(map_num)
            else:
                # Fallback to watcher's watched set
                watched = self.watcher.watched if self.watcher else set()
            
            live_set = set(self.live_maps) if hasattr(self, 'live_maps') else set()
            if self.watcher and hasattr(self.watcher, 'state'):
                live_set = set(self.watcher.state.get_live_summary(watched, set(), now_ts))
            
            for mn in sorted(watched):
                # Check single ETA for non-live maps
                if mn not in live_set:
                    eta_sec = BIG
                    line = f"- {mn} will be live in unknown"
                    
                    # Check single ETA
                    if mn in self.watcher.state.eta_seconds_by_map:
                        eta_sec = self.watcher.state.eta_seconds_by_map[mn]
                        srv = self.watcher.state.server_by_map.get(mn, "")
                        if srv:
                            line = f"- {mn} will be live in {eta_sec//60}:{eta_sec%60:02d} on {srv}"
                        else:
                            line = f"- {mn} will be live in {eta_sec//60}:{eta_sec%60:02d}"
                    
                    # Check upcoming servers
                    if mn in self.watcher.state.upcoming_by_map:
                        for s, sec in self.watcher.state.upcoming_by_map[mn]:
                            if sec < eta_sec:
                                eta_sec = sec
                                if s:
                                    line = f"- {mn} will be live in {sec//60}:{sec%60:02d} on {s}"
                                else:
                                    line = f"- {mn} will be live in {sec//60}:{sec%60:02d}"
                    
                    tracked_display_lines.append((eta_sec, line))
                
                # For live maps, also show upcoming servers (different server, scheduled later)
                if mn in live_set and mn in self.watcher.state.upcoming_by_map:
                    for s, sec in self.watcher.state.upcoming_by_map[mn]:
                        if sec > 0:  # Only show if there's an actual ETA
                            tracked_display_lines.append((sec, f"- {mn} will be live in {sec//60}:{sec%60:02d} on {s}"))
            
            # Sort by ETA
            for _, line in sorted(tracked_display_lines, key=lambda x: x[0]):
                self.output_text.insert(tk.END, f"{line}\n")
            
            if not tracked_display_lines:
                self.output_text.insert(tk.END, "(none)\n")
        elif self.tracked_lines:
            # Fallback to stored tracked_lines if watcher not available
            for _, line in sorted(self.tracked_lines, key=lambda x: x[0]):
                self.output_text.insert(tk.END, f"{line}\n")
        else:
            self.output_text.insert(tk.END, "(none)\n")
        
        # Configure text tags for styling
        self.output_text.tag_config("live_header", font=("Consolas", 10, "bold"), foreground="green")
        self.output_text.tag_config("tracked_header", font=("Consolas", 10, "bold"), foreground="blue")
        
        self.output_text.config(state=tk.DISABLED)
        # Auto-scroll to top
        self.output_text.see("1.0")
    
    def start_countdown_timer(self) -> None:
        """Start the countdown timer that updates display every second."""
        if self.countdown_timer_id:
            self.root.after_cancel(self.countdown_timer_id)
        
        def countdown_update():
            """Update display with current countdown values."""
            if self.watcher:
                # Update ETAs in state by counting down by 1 second since last update
                now = time.time()
                if self.last_countdown_update > 0:
                    elapsed = now - self.last_countdown_update
                    if elapsed >= 1.0:
                        # Countdown by approximately 1 second
                        self.watcher.state.countdown_etas(1)
                        self.last_countdown_update = now
                else:
                    self.last_countdown_update = now
            
            self._refresh_display()
            
            # Schedule next update
            self.countdown_timer_id = self.root.after(1000, countdown_update)
        
        # Start the timer
        self.countdown_timer_id = self.root.after(1000, countdown_update)
    
    def start_watcher(self) -> None:
        """Start the watcher in a separate thread."""
        if self.running:
            return
        
        self.running = True
        
        def watcher_loop():
            """Watcher thread main loop."""
            self.watcher = KackyWatcher(
                config=self.config,
                on_status_update=lambda msg: self.root.after(0, lambda: self.update_status(msg)),
                on_live_notification=self.on_live_notification,
                on_summary_update=self.on_summary_update,
            )
            # Override run to use poll_once in a loop we can control
            while self.running:
                try:
                    # Check if immediate fetch is requested
                    immediate_fetch = self.immediate_fetch_event.is_set()
                    if immediate_fetch:
                        self.immediate_fetch_event.clear()
                    
                    self.watcher.poll_once()
                    self.last_fetch_timestamp = time.time()
                    self.last_countdown_update = time.time()  # Reset countdown timer on fetch
                    
                    # Calculate next fetch time dynamically
                    next_fetch_sec = self.watcher.calculate_next_fetch_time(time.time())
                    if next_fetch_sec > 0:
                        # Sleep in smaller intervals to allow interruption
                        sleep_interval = 0.5  # Check every 0.5 seconds
                        slept = 0.0
                        while slept < next_fetch_sec and self.running and not self.immediate_fetch_event.is_set():
                            time.sleep(sleep_interval)
                            slept += sleep_interval
                    else:
                        # If no fetch time calculated, use minimal sleep
                        time.sleep(0.5)
                except Exception as e:
                    self.root.after(0, lambda: self.update_status(f"Watcher error: {e}"))
                    time.sleep(1)
        
        self.watcher_thread = threading.Thread(target=watcher_loop, daemon=True)
        self.watcher_thread.start()
        self.update_status("Watcher started")
    
    def stop_watcher(self) -> None:
        """Stop the watcher."""
        self.running = False
        if self.watcher_thread:
            self.watcher_thread.join(timeout=2.0)
        self.update_status("Watcher stopped")
    
    def on_closing(self) -> None:
        """Handle window closing."""
        self.save_map_status()
        self.stop_watcher()
        self.root.destroy()
    
    def run(self) -> None:
        """Start the GUI event loop."""
        self.root.mainloop()


def main() -> None:
    """Main entry point for GUI mode."""
    try:
        print("Starting Kacky Watcher GUI...")
        root = tk.Tk()
        print("Root window created")
        app = KackyWatcherGUI(root)
        print("GUI initialized, starting event loop...")
        root.update()  # Force initial render
        print("Window should be visible now")
        app.run()
    except Exception as e:
        import traceback
        print(f"Error launching GUI: {e}")
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
