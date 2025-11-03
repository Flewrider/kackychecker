"""
GUI module for Kacky Watcher using tkinter.
Provides split-pane interface with map list (tracking/finished checkboxes) and live/tracked output.
"""
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
        
        # Current state for display
        self.live_maps: List[int] = []
        self.tracked_lines: List[Tuple[int, str]] = []
        
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
        
        # Column headers
        header_row = ttk.Frame(left_frame)
        header_row.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(header_row, text="Map", width=8, font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=2)
        ttk.Label(header_row, text="Tracking", width=10, font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=2)
        ttk.Label(header_row, text="Finished", width=10, font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=2)
        
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
        
        # Only bind mouse wheel to this canvas, not all widgets
        canvas.bind("<MouseWheel>", on_mousewheel)
        
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
            # Clear existing rows and checkbox variables
            for widget in self.map_container.winfo_children():
                widget.destroy()
            
            self.map_rows.clear()
            # Clear checkbox variables to start fresh
            self.tracking_vars.clear()
            self.finished_vars.clear()
            
            # Get current status
            tracking = get_tracking_maps(self.status_file)
            finished = get_finished_maps(self.status_file)
            
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
                self.add_map_row(map_num, map_num in tracking, map_num in finished, is_finished=True)
            
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
        
        row_frame.pack(fill=tk.X, pady=1)
        
        # Map number label
        if bg_color:
            map_label = tk.Label(row_frame, text=str(map_num), width=8, anchor=tk.CENTER, bg=bg_color)
        else:
            map_label = ttk.Label(row_frame, text=str(map_num), width=8, anchor=tk.CENTER)
        map_label.pack(side=tk.LEFT, padx=2)
        
        # Tracking checkbox - create without command first, set value, then add command
        tracking_cb = ttk.Checkbutton(row_frame, variable=self.tracking_vars[map_num])
        tracking_cb.pack(side=tk.LEFT, padx=2)
        # Now set the command after the variable is set
        tracking_cb.configure(command=lambda mn=map_num: self.on_checkbox_change(mn, "tracking"))
        
        # Finished checkbox - create without command first, set value, then add command
        finished_cb = ttk.Checkbutton(row_frame, variable=self.finished_vars[map_num])
        finished_cb.pack(side=tk.LEFT, padx=2)
        # Now set the command after the variable is set
        finished_cb.configure(command=lambda mn=map_num: self.on_checkbox_change(mn, "finished"))
        
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
        
        # If finished checkbox was checked, refresh the list to move it to bottom
        if checkbox_type == "finished":
            # Schedule repopulation after a short delay to avoid immediate re-trigger
            self.root.after(50, self.populate_map_list)
        
        # Schedule save after 0.5 seconds of no changes
        self.save_timer = self.root.after(500, self.save_map_status)
        
        # Update watcher if tracking changed
        if checkbox_type == "tracking" and self.watcher:
            self.watcher.watched = get_tracking_maps(self.status_file)
            self.watcher.watchlist_added = True
    
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
        
        self.output_text.config(state=tk.NORMAL)
        self.output_text.delete("1.0", tk.END)
        
        # Format live section
        if live_maps:
            self.output_text.insert(tk.END, "Live:\n", "live_header")
            for mn in live_maps:
                # Get servers and remaining time from watcher state
                servers = []
                remaining_sec = 0
                if self.watcher and hasattr(self.watcher, 'state'):
                    servers = sorted(self.watcher.state.live_servers_by_map.get(mn, set()))
                    if mn in self.watcher.state.live_until_by_map:
                        remaining_sec = max(0, int(self.watcher.state.live_until_by_map[mn] - time.time()))
                
                remaining_str = f" ({remaining_sec//60}:{remaining_sec%60:02d} remaining)" if remaining_sec > 0 else ""
                if servers:
                    self.output_text.insert(tk.END, f"- {mn} on {', '.join(servers)}{remaining_str}\n")
                else:
                    self.output_text.insert(tk.END, f"- {mn}{remaining_str}\n")
            self.output_text.insert(tk.END, "\n")
        else:
            self.output_text.insert(tk.END, "Live:\n(none)\n\n")
        
        # Format tracked section
        self.output_text.insert(tk.END, "Tracked:\n", "tracked_header")
        if tracked_lines:
            # Sort by ETA (unknowns last)
            for _, line in sorted(tracked_lines, key=lambda x: x[0]):
                self.output_text.insert(tk.END, f"{line}\n")
        else:
            self.output_text.insert(tk.END, "(none)\n")
        
        # Configure text tags for styling
        self.output_text.tag_config("live_header", font=("Consolas", 10, "bold"), foreground="green")
        self.output_text.tag_config("tracked_header", font=("Consolas", 10, "bold"), foreground="blue")
        
        self.output_text.config(state=tk.DISABLED)
        # Auto-scroll to top
        self.output_text.see("1.0")
    
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
                    self.watcher.poll_once()
                    sleep_sec = max(1, self.config["WATCHLIST_REFRESH_SECONDS"])
                    time.sleep(sleep_sec)
                except Exception as e:
                    self.root.after(0, lambda: self.update_status(f"Watcher error: {e}"))
                    time.sleep(self.config["WATCHLIST_REFRESH_SECONDS"])
        
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
