"""
GUI module for Kacky Watcher using tkinter.
Provides split-pane interface with map list (tracking/finished checkboxes) and live/tracked output.
"""
import logging
import queue
import threading
import time
from typing import List, Set, Tuple, Optional, Dict, Any

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from config import load_config, setup_logging
from watcher_core import KackyWatcher
from map_status_manager import save_map_status, get_tracking_maps, get_finished_maps
from settings_manager import load_settings, save_settings, get_default_settings
from path_utils import get_map_status_file
from playwright_installer import check_browsers_installed, install_browsers_with_progress

# Windows notifications
try:
    from windows_notifications import HAS_NOTIFICATIONS, show_notification_async
except ImportError:
    HAS_NOTIFICATIONS = False
    def show_notification_async(title: str, message: str, duration: int = 5) -> None:
        pass


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
        
        # Windows notifications are handled via windows_notifications module
        # No instance needed - use show_notification_async() function directly
        
        print("Loading config...")
        self.config = load_config()
        print("Setting up logging...")
        setup_logging(self.config["LOG_LEVEL"])
        print("Config and logging complete")
        
        # CRITICAL: Set Playwright browsers path BEFORE any Playwright imports or operations
        # This must happen early to ensure Playwright can find browsers installed by system Python
        # Must be before check_and_install_playwright() or any code that imports Playwright
        try:
            from playwright_installer import _ensure_browsers_path_set
            _ensure_browsers_path_set()
            logging.debug("Set Playwright browsers path at GUI startup (before any Playwright operations)")
        except Exception as e:
            # Log but don't fail - this is best effort
            logging.debug(f"Could not ensure browsers path at startup: {e}", exc_info=True)
        
        # Map status file path
        self.status_file = get_map_status_file()
        
        # Map range
        self.map_range_start = 376
        self.map_range_end = 450
        
        # Debounce timer for status saving
        self.save_timer: Optional[str] = None
        
        # Watcher thread
        self.watcher: Optional[KackyWatcher] = None
        self.watcher_thread: Optional[threading.Thread] = None
        self.running = False
        self.immediate_fetch_event = threading.Event()  # Signal to trigger immediate fetch
        
        # Queue for thread-safe GUI updates (decouple watcher from GUI rendering)
        self.update_queue: queue.Queue = queue.Queue(maxsize=100)  # Limit queue size
        self.last_refresh_time: float = 0.0  # Throttle refresh calls
        self.refresh_throttle_ms: float = 50.0  # Minimum ms between refreshes
        self.pending_refresh: bool = False  # Flag to indicate refresh is needed
        self.refresh_timer_id: Optional[str] = None  # ID of pending refresh timer
        
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
            
            # Create menu bar after UI setup
            menubar = tk.Menu(self.root)
            self.root.config(menu=menubar)
            
            # Settings menu
            settings_menu = tk.Menu(menubar, tearoff=0)
            menubar.add_cascade(label="Settings", menu=settings_menu)
            settings_menu.add_command(label="Configure...", command=self.show_settings_dialog)
            
            # Initialize default files on first run
            self.initialize_default_files()
            
            # Check and install Playwright browsers if needed
            # Note: _ensure_browsers_path_set() was already called at the start of __init__
            self.check_and_install_playwright()
            
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
        
        # Left pane: Map list with checkboxes (with border)
        left_frame = tk.Frame(main_paned, relief=tk.SOLID, borderwidth=1, bg="black")
        main_paned.add(left_frame, weight=1)
        
        # Inner frame for left pane content
        left_inner = ttk.Frame(left_frame)
        left_inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        
        # Header
        header_frame = ttk.Frame(left_inner)
        header_frame.pack(fill=tk.X, padx=5, pady=(5, 2))
        ttk.Label(header_frame, text="Maps", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        
        # Column headers - use grid for better alignment
        # Calculate padding from left_inner to container's left edge:
        # map_paned padx=5 + outer_frame border=1 + inner_frame padx=1 + canvas_frame padx=5 = 12px
        # Container is positioned at x=0 within canvas, which is at the left edge of canvas_frame
        # So header should be at 12px from left_inner to match container content
        header_row = ttk.Frame(left_inner)
        header_row.pack(fill=tk.X, padx=12, pady=2)  # Match container position: 5+1+1+5=12px
        
        # Use fixed column widths that match row widgets exactly
        # Use padx=(0, 2) to only add right padding, ensuring left alignment
        # Map column - fixed width frame
        map_header_frame = ttk.Frame(header_row, width=70)
        map_header_frame.grid(row=0, column=0, padx=(0, 2), sticky=tk.W)
        map_header_frame.grid_propagate(False)
        ttk.Label(map_header_frame, text="Map", width=8, font=("Arial", 9, "bold")).pack(anchor=tk.W)
        
        # Tracking column - fixed width frame
        tracking_header_frame = ttk.Frame(header_row, width=90)
        tracking_header_frame.grid(row=0, column=1, padx=(0, 2), sticky=tk.W)
        tracking_header_frame.grid_propagate(False)
        ttk.Label(tracking_header_frame, text="Tracking", width=10, font=("Arial", 9, "bold")).pack(anchor=tk.W)
        
        # Finished column - fixed width frame
        finished_header_frame = ttk.Frame(header_row, width=90)
        finished_header_frame.grid(row=0, column=2, padx=(0, 2), sticky=tk.W)
        finished_header_frame.grid_propagate(False)
        ttk.Label(finished_header_frame, text="Finished", width=10, font=("Arial", 9, "bold")).pack(anchor=tk.W)
        
        # Configure grid columns with exact widths
        header_row.grid_columnconfigure(0, weight=0, minsize=70)
        header_row.grid_columnconfigure(1, weight=0, minsize=90)
        header_row.grid_columnconfigure(2, weight=0, minsize=90)
        
        # Create resizable paned window for unfinished and finished sections
        map_paned = ttk.PanedWindow(left_inner, orient=tk.VERTICAL)
        map_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Helper function to create scrollable frame
        def create_scrollable_frame(parent, label_text=None):
            """Create a scrollable frame with canvas and scrollbar."""
            # Outer frame with border
            outer_frame = tk.Frame(parent, relief=tk.SOLID, borderwidth=1, bg="black")
            outer_frame.pack(fill=tk.BOTH, expand=True)
            
            # Inner frame for content
            frame = ttk.Frame(outer_frame)
            frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
            
            # Add consistent vertical spacing for label area (even if no label)
            # Use consistent padding for both sections
            label_area = ttk.Frame(frame)
            label_area.pack(fill=tk.X, padx=5, pady=(5, 2))  # Same padding for both sections
            if label_text:
                label = ttk.Label(label_area, text=label_text, font=("Arial", 9, "bold"))
                label.pack(anchor=tk.W)
            # If no label, label_area still exists but is empty (provides consistent spacing)
            
            # Canvas frame with consistent padding - must match header alignment
            canvas_frame = ttk.Frame(frame)
            canvas_frame.pack(fill=tk.BOTH, expand=True, padx=5)  # Same padding as label_area
            
            canvas = tk.Canvas(canvas_frame, highlightthickness=0)
            scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
            # Container with no padding - rows will be added directly
            container = ttk.Frame(canvas)
            
            # Position container at exact same position (x=0) for both sections
            # Use anchor=tk.NW and x=0 to ensure consistent left alignment
            canvas_window = canvas.create_window(0, 0, window=container, anchor=tk.NW)
            
            def configure_scroll_region(event):
                canvas.configure(scrollregion=canvas.bbox("all"))
            
            def configure_canvas_width(event):
                canvas_width = event.width
                # Set container width to match canvas width exactly
                canvas.itemconfig(canvas_window, width=canvas_width)
                # Explicitly position container at x=0 to ensure consistent alignment between sections
                canvas.coords(canvas_window, 0, 0)
            
            container.bind("<Configure>", configure_scroll_region)
            canvas.bind("<Configure>", configure_canvas_width)
            
            canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            canvas.configure(yscrollcommand=scrollbar.set)
            
            # Mouse wheel scrolling
            def on_mousewheel(event):
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            
            def bind_mousewheel(widget):
                widget.bind("<MouseWheel>", on_mousewheel)
                for child in widget.winfo_children():
                    bind_mousewheel(child)
            
            canvas.bind("<MouseWheel>", on_mousewheel)
            canvas_frame.bind("<MouseWheel>", on_mousewheel)
            container.bind("<MouseWheel>", on_mousewheel)
            bind_mousewheel(container)
            
            return outer_frame, canvas, container
        
        # Unfinished maps section (top)
        unfinished_frame, self.unfinished_canvas, self.unfinished_container = create_scrollable_frame(map_paned)
        map_paned.add(unfinished_frame, weight=3)  # Give more space to unfinished maps
        
        # Finished maps section (bottom)
        finished_frame, self.finished_canvas, self.finished_container = create_scrollable_frame(map_paned, "Finished Maps")
        map_paned.add(finished_frame, weight=1)  # Less space for finished maps
        
        # Store references for backward compatibility
        self.map_container = self.unfinished_container  # For backward compatibility
        self.map_canvas = self.unfinished_canvas  # For backward compatibility
        
        # Right pane: Output display (with border)
        right_frame = tk.Frame(main_paned, relief=tk.SOLID, borderwidth=1, bg="black")
        main_paned.add(right_frame, weight=1)
        
        # Inner frame for right pane content
        right_inner = ttk.Frame(right_frame)
        right_inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        
        ttk.Label(right_inner, text="Live & Tracked Maps", font=("Arial", 10, "bold")).pack(anchor=tk.W, padx=5, pady=(5, 2))
        
        self.output_text = scrolledtext.ScrolledText(
            right_inner,
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
            for widget in self.unfinished_container.winfo_children():
                widget.destroy()
            for widget in self.finished_container.winfo_children():
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
            # Add unfinished maps to unfinished container
            for i, map_num in enumerate(unfinished_maps):
                if i % 20 == 0:
                    print(f"  Added {i}/{len(unfinished_maps)} unfinished maps...")
                self.add_map_row(map_num, map_num in tracking, map_num in finished, container=self.unfinished_container)
            
            print(f"Adding {len(finished_maps)} finished maps...")
            # Add finished maps to finished container (green background)
            for map_num in finished_maps:
                self.add_map_row(map_num, map_num in tracking, map_num in finished, is_finished_flag=True, container=self.finished_container)
            
            # Rebind mouse wheel to new widgets in both containers
            def bind_mousewheel(widget, target_canvas):
                widget.bind("<MouseWheel>", lambda e: target_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
                for child in widget.winfo_children():
                    bind_mousewheel(child, target_canvas)
            bind_mousewheel(self.unfinished_container, self.unfinished_canvas)
            bind_mousewheel(self.finished_container, self.finished_canvas)
            
            print("Map list population complete")
        finally:
            self._populating = False
    
    def add_map_row(self, map_num: int, is_tracking: bool, is_finished: bool, is_finished_flag: bool = False, container: Optional[tk.Widget] = None) -> None:
        """
        Add a map row to the list.
        
        Args:
            map_num: Map number
            is_tracking: Whether map is being tracked
            is_finished: Whether map is finished
            is_finished_flag: Whether this is being added as a finished map (for styling)
            container: Container widget to add the row to (defaults to unfinished_container)
        """
        # Use specified container or default to unfinished
        if container is None:
            container = self.unfinished_container
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
            row_frame = tk.Frame(container, bg="#90EE90")  # Light green
            bg_color = "#90EE90"
        else:
            row_frame = ttk.Frame(container)
            bg_color = None
        
        # Use grid layout for consistent alignment regardless of window size
        # Match column widths exactly with header
        row_frame.grid_columnconfigure(0, weight=0, minsize=70)  # Match header column 0
        row_frame.grid_columnconfigure(1, weight=0, minsize=90)  # Match header column 1
        row_frame.grid_columnconfigure(2, weight=0, minsize=90)  # Match header column 2
        
        # Map number label - use fixed width frame for consistent alignment
        # Use padx=(0, 2) to match header - only right padding, no left padding
        map_label_frame = ttk.Frame(row_frame, width=70)  # Match header column width
        map_label_frame.grid(row=0, column=0, padx=(0, 2), sticky=tk.W)
        map_label_frame.grid_propagate(False)  # Don't let children resize frame
        
        if bg_color:
            map_label = tk.Label(map_label_frame, text=str(map_num), width=8, anchor=tk.CENTER, bg=bg_color)
        else:
            map_label = ttk.Label(map_label_frame, text=str(map_num), width=8, anchor=tk.CENTER)
        map_label.pack(anchor=tk.W)
        
        # Tracking checkbox - use grid for alignment with fixed width frame
        # Use padx=(0, 2) to match header - only right padding
        tracking_frame = ttk.Frame(row_frame, width=90)
        tracking_frame.grid(row=0, column=1, padx=(0, 2), sticky=tk.W)
        tracking_frame.grid_propagate(False)
        tracking_cb = ttk.Checkbutton(tracking_frame, variable=self.tracking_vars[map_num])
        tracking_cb.pack(anchor=tk.W)
        # Now set the command after the variable is set
        tracking_cb.configure(command=lambda mn=map_num: self.on_checkbox_change(mn, "tracking"))
        
        # Finished checkbox - use grid for alignment with fixed width frame
        # Use padx=(0, 2) to match header - only right padding
        finished_frame_cb = ttk.Frame(row_frame, width=90)
        finished_frame_cb.grid(row=0, column=2, padx=(0, 2), sticky=tk.W)
        finished_frame_cb.grid_propagate(False)
        finished_cb = ttk.Checkbutton(finished_frame_cb, variable=self.finished_vars[map_num])
        finished_cb.pack(anchor=tk.W)
        # Now set the command after the variable is set
        finished_cb.configure(command=lambda mn=map_num: self.on_checkbox_change(mn, "finished"))
        
        # Pack the row frame itself - no horizontal padding to ensure alignment
        row_frame.pack(fill=tk.X, pady=1, padx=0)
        
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
                # Schedule refresh (non-blocking, allows GUI to process resize events)
                self._schedule_refresh()
    
    def initialize_default_files(self) -> None:
        """Initialize default files on first run if they don't exist."""
        import os
        from path_utils import get_settings_file, get_map_status_file
        from settings_manager import get_default_settings, save_settings
        
        # Initialize settings.json if it doesn't exist
        settings_path = get_settings_file()
        if not os.path.exists(settings_path):
            default_settings = get_default_settings()
            save_settings(default_settings)
            logging.debug("Created default settings.json")
        
        # Initialize map_status.json if it doesn't exist (empty state)
        status_path = get_map_status_file()
        if not os.path.exists(status_path):
            save_map_status(set(), set(), status_path)
            logging.debug("Created default map_status.json")
    
    def check_and_install_playwright(self) -> None:
        """Check if Playwright browsers are installed and install if needed."""
        # Playwright browsers are required for the application to work
        # since HTTP requests don't return usable data
        logging.debug("Checking Playwright browser installation...")
        try:
            browsers_installed = check_browsers_installed()
            logging.debug(f"Browsers installed check result: {browsers_installed}")
            
            if not browsers_installed:
                logging.debug("Playwright browsers not found, showing installation dialog...")
                
                # Show dialog - installation is required
                response = messagebox.askyesno(
                    "Install Playwright Browsers (Required)",
                    "Playwright browsers are REQUIRED for this application to work.\n\n"
                    "The website requires JavaScript rendering, so HTTP requests alone\n"
                    "cannot gather the schedule data.\n\n"
                    "The installation will download ~100-200MB and may take a few minutes.\n\n"
                    "Would you like to install them now?\n\n"
                    "The application cannot function properly without them.",
                    icon="warning"
                )
                
                logging.debug(f"User response to installation dialog: {response}")
                
                if response:
                    logging.debug("User chose to install, starting installation thread...")
                    # Force GUI update immediately (on main thread)
                    self.update_status("Preparing installation...")
                    
                    # Install in a separate thread to avoid blocking GUI
                    def install_thread():
                        try:
                            logging.debug("=== INSTALLATION THREAD STARTED ===")
                            
                            def update_status(message: str):
                                """Update status from background thread - safely schedules on main thread."""
                                logging.debug(f"Status update: {message}")
                                # Schedule update on main thread - capture message in default arg for safety
                                try:
                                    # Use a closure with default argument to capture the message
                                    def update_on_main(msg=message):
                                        try:
                                            self.update_status(msg)
                                        except Exception as e:
                                            logging.error(f"Error updating status: {e}")
                                    
                                    self.root.after(0, update_on_main)
                                except Exception as e:
                                    logging.error(f"Error scheduling status update: {e}")
                            
                            # Initial status update
                            update_status("Starting Playwright browser installation...")
                            logging.debug("Calling install_browsers_with_progress...")
                            
                            success, error = install_browsers_with_progress(update_status)
                            
                            logging.debug(f"=== Installation result: success={success}, error={error} ===")
                            
                            if success:
                                logging.debug("Installation succeeded, verifying...")
                                # Re-check browsers after installation
                                import time
                                time.sleep(2)  # Give installation time to complete
                                browsers_now_installed = check_browsers_installed()
                                logging.debug(f"Re-check after installation: {browsers_now_installed}")
                                
                                # Trigger immediate fetch after successful installation
                                # This ensures the user doesn't have to wait for the scheduled refetch
                                logging.debug("Triggering immediate fetch after browser installation...")
                                self.immediate_fetch_event.set()
                                
                                def show_success(verified=browsers_now_installed):
                                    try:
                                        if verified:
                                            messagebox.showinfo(
                                                "Installation Complete",
                                                "Playwright browsers installed successfully!\n"
                                                "The application can now fetch schedule data.\n\n"
                                                "Fetching schedule data now..."
                                            )
                                        else:
                                            messagebox.showwarning(
                                                "Installation Complete",
                                                "Playwright browsers installation completed.\n\n"
                                                "The browsers may not be detected until you restart the application.\n"
                                                "Please restart the application to use the browser features."
                                            )
                                    except Exception as e:
                                        logging.error(f"Error showing success dialog: {e}")
                                self.root.after(0, show_success)
                            else:
                                error_display = error or "Unknown error occurred"
                                logging.error(f"Installation failed: {error_display}")
                                def show_error(err=error_display):
                                    try:
                                        messagebox.showerror(
                                            "Installation Failed",
                                            f"Failed to install Playwright browsers:\n\n{err}\n\n"
                                            "The application will not be able to fetch schedule data.\n"
                                            "Please try installing again or check your internet connection.\n\n"
                                            "You can also try installing manually:\n"
                                            "python -m playwright install chromium"
                                        )
                                    except Exception as e:
                                        logging.error(f"Error showing error dialog: {e}")
                                self.root.after(0, show_error)
                        except Exception as e:
                            logging.error(f"=== UNEXPECTED ERROR in install thread: {e} ===", exc_info=True)
                            import traceback
                            error_trace = traceback.format_exc()
                            logging.error(f"Full traceback:\n{error_trace}")
                            def show_exception_error(err=str(e), trace=error_trace):
                                try:
                                    messagebox.showerror(
                                        "Installation Error",
                                        f"An unexpected error occurred during installation:\n\n{err}\n\n"
                                        f"Check logs for details:\n{trace[:500]}"
                                    )
                                except Exception as e2:
                                    logging.error(f"Error showing exception dialog: {e2}")
                            self.root.after(0, show_exception_error)
                    
                    install_thread_obj = threading.Thread(target=install_thread, daemon=False, name="PlaywrightInstaller")
                    install_thread_obj.start()
                    logging.debug(f"Installation thread started: {install_thread_obj.name}, alive={install_thread_obj.is_alive()}")
                else:
                    logging.warning("User skipped required Playwright browser installation")
                    messagebox.showwarning(
                        "Installation Skipped",
                        "Playwright browsers are REQUIRED for the application to work.\n\n"
                        "The application will not be able to fetch schedule data without them.\n"
                        "Please restart the application and install them when prompted."
                    )
            else:
                logging.debug("Playwright browsers are already installed")
        except Exception as e:
            logging.warning(f"Error checking/installing Playwright browsers: {e}")
            # Don't block startup if this fails, but warn the user
            messagebox.showwarning(
                "Playwright Check Failed",
                f"Could not verify Playwright browser installation:\n{e}\n\n"
                "The application may not function properly."
            )
    
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
            # Also save server uptimes if watcher state is available
            server_uptimes = None
            if hasattr(self, 'watcher') and self.watcher and hasattr(self.watcher.state, 'server_uptime_seconds'):
                server_uptimes = self.watcher.state.server_uptime_seconds
            
            save_map_status(tracking, finished, self.status_file, server_uptimes)
            self.update_status("Map status saved")
        except Exception as e:
            self.update_status(f"Error saving map status: {e}")
    
    def update_status(self, message: str) -> None:
        """
        Update status bar (called on main thread).
        
        Args:
            message: Status message to display
        """
        timestamp = time.strftime("%H:%M:%S")
        self.status_label.config(text=f"[{timestamp}] {message}")
    
    def _queue_status_update(self, message: str) -> None:
        """
        Queue a status update from watcher thread (non-blocking).
        
        Args:
            message: Status message to display
        """
        try:
            self.update_queue.put_nowait(("status", {"message": message}))
        except queue.Full:
            pass  # Queue full, skip this update
    
    def _start_queue_processor(self) -> None:
        """Start processing updates from the queue on the main thread."""
        def process_queue():
            """Process all available queue items (called on main thread)."""
            processed_count = 0
            max_items_per_cycle = 10  # Limit items per cycle to avoid blocking
            
            while processed_count < max_items_per_cycle:
                try:
                    update_type, data = self.update_queue.get_nowait()
                    
                    if update_type == "summary":
                        self._update_output(data["live_maps"], data["tracked_lines"])
                    elif update_type == "live_notification":
                        self._show_live_notification(data["map_number"], data["server"])
                    elif update_type == "status":
                        self.update_status(data["message"])
                    
                    processed_count += 1
                except queue.Empty:
                    break
            
            # Schedule next check (use after_idle to process during GUI idle time)
            if processed_count > 0:
                # If we processed items, check again soon
                self.root.after(10, process_queue)
            else:
                # If queue is empty, check less frequently
                self.root.after(100, process_queue)
        
        # Start processing
        self.root.after_idle(process_queue)
    
    def on_live_notification(self, map_number: int, server: str) -> None:
        """
        Handle live map notification.
        
        Args:
            map_number: Map number that went live
            server: Server name or empty string
        """
        # Put notification in queue (non-blocking)
        try:
            self.update_queue.put_nowait(("live_notification", {"map_number": map_number, "server": server}))
        except queue.Full:
            pass  # Queue full, skip this update
    
    def _show_live_notification(self, map_number: int, server: str) -> None:
        """Show live notification in GUI (called on main thread from queue processor)."""
        server_text = f" on {server}" if server else ""
        logging.debug(f"_show_live_notification called for map #{map_number}, server: {server}")
        self.update_status(f"🎉 Map #{map_number} is LIVE{server_text}!")
        
        # Check notification settings
        notifications_enabled = self.config.get("ENABLE_NOTIFICATIONS", True)
        logging.debug(f"Notifications enabled: {notifications_enabled}, HAS_NOTIFICATIONS: {HAS_NOTIFICATIONS}")
        
        # Show Windows notification if enabled
        if notifications_enabled and HAS_NOTIFICATIONS:
            try:
                title = f"Map #{map_number} is LIVE!"
                message = f"Map #{map_number} is now live{server_text}"
                logging.debug(f"Attempting to show notification: title='{title}', message='{message}'")
                # Show notification asynchronously (runs in separate thread)
                show_notification_async(title, message, duration=5)
                logging.debug("Notification request sent")
            except Exception as e:
                logging.error(f"Failed to show notification: {e}", exc_info=True)
        else:
            if not notifications_enabled:
                logging.debug("Notifications disabled in settings")
            if not HAS_NOTIFICATIONS:
                logging.debug("Windows notifications not available (HAS_NOTIFICATIONS=False)")
        
        # Transition refetches removed - maps can appear live on different servers immediately
    
    def on_summary_update(self, live_maps: List[int], tracked_lines: List[Tuple[int, str]]) -> None:
        """
        Handle summary update from watcher.
        
        Args:
            live_maps: List of live map numbers
            tracked_lines: List of (eta_seconds, line_text) tuples
        """
        # Put update in queue instead of directly calling GUI (non-blocking)
        try:
            self.update_queue.put_nowait(("summary", {"live_maps": live_maps, "tracked_lines": tracked_lines}))
        except queue.Full:
            pass  # Queue full, skip this update
    
    def _update_output(self, live_maps: List[int], tracked_lines: List[Tuple[int, str]]) -> None:
        """Update output display (called on main thread)."""
        self.live_maps = live_maps
        self.tracked_lines = tracked_lines
        # Schedule refresh instead of immediate (allows GUI to process resize events)
        self._schedule_refresh()
    
    def _schedule_refresh(self) -> None:
        """Schedule a display refresh (throttled to avoid blocking GUI)."""
        if self.pending_refresh:
            return  # Already scheduled
        
        now_ms = time.time() * 1000
        time_since_last = now_ms - (self.last_refresh_time * 1000)
        
        if time_since_last >= self.refresh_throttle_ms:
            # Enough time has passed, refresh immediately on next idle
            self.pending_refresh = True
            if self.refresh_timer_id:
                self.root.after_cancel(self.refresh_timer_id)
            self.root.after_idle(self._process_refresh)
        else:
            # Schedule refresh after throttle period
            delay_ms = int(self.refresh_throttle_ms - time_since_last)
            self.pending_refresh = True
            if self.refresh_timer_id:
                self.root.after_cancel(self.refresh_timer_id)
            self.refresh_timer_id = self.root.after(delay_ms, self._process_refresh)
    
    def _process_refresh(self) -> None:
        """Process the scheduled refresh (called on main thread)."""
        self.pending_refresh = False
        self.refresh_timer_id = None
        self.last_refresh_time = time.time()
        self._refresh_display()
    
    def _refresh_display(self) -> None:
        """Refresh the display with current countdown values (called on main thread)."""
        now_ts = time.time()
        
        # Build content as string first (much faster than multiple inserts)
        content_lines = []
        
        self.output_text.config(state=tk.NORMAL)
        
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
                content_lines.append(("Live:\n", "live_header"))
                for mn in live_summary:
                    # Get servers and remaining time from watcher state
                    servers = sorted(self.watcher.state.live_servers_by_map.get(mn, set()))
                    remaining_sec = 0
                    if mn in self.watcher.state.live_until_by_map:
                        remaining_sec = max(0, int(self.watcher.state.live_until_by_map[mn] - now_ts))
                    
                    remaining_str = f" ({remaining_sec//60}:{remaining_sec%60:02d} remaining)" if remaining_sec > 0 else ""
                    if servers:
                        content_lines.append((f"- {mn} on {', '.join(servers)}{remaining_str}\n", None))
                    else:
                        content_lines.append((f"- {mn}{remaining_str}\n", None))
                content_lines.append(("\n", None))
            else:
                content_lines.append(("Live:\n(none)\n\n", None))
        elif self.live_maps:
            content_lines.append(("Live:\n", "live_header"))
            for mn in self.live_maps:
                content_lines.append((f"- {mn}\n", None))
            content_lines.append(("\n", None))
        else:
            content_lines.append(("Live:\n(none)\n\n", None))
        
        # Format tracked section
        content_lines.append(("Tracked:\n", "tracked_header"))
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
                    
                    # Check if ETA is stuck at 000 (indicating stale data)
                    if eta_sec == 0 and eta_sec != BIG:
                        # Check if data is stale (no recent successful fetch)
                        if hasattr(self.watcher, 'last_successful_fetch_time'):
                            time_since_success = now_ts - self.watcher.last_successful_fetch_time if self.watcher.last_successful_fetch_time > 0 else float('inf')
                            if time_since_success > 120:  # More than 2 minutes since last success
                                line += " ⚠️ (stale data)"
                    
                    tracked_display_lines.append((eta_sec, line))
                
                # For live maps, also show upcoming servers (different server, scheduled later)
                if mn in live_set and mn in self.watcher.state.upcoming_by_map:
                    for s, sec in self.watcher.state.upcoming_by_map[mn]:
                        if sec > 0:  # Only show if there's an actual ETA
                            tracked_display_lines.append((sec, f"- {mn} will be live in {sec//60}:{sec%60:02d} on {s}"))
            
            # Sort by ETA
            for _, line in sorted(tracked_display_lines, key=lambda x: x[0]):
                content_lines.append((f"{line}\n", None))
            
            if not tracked_display_lines:
                content_lines.append(("(none)\n", None))
        elif self.tracked_lines:
            # Fallback to stored tracked_lines if watcher not available
            for _, line in sorted(self.tracked_lines, key=lambda x: x[0]):
                content_lines.append((f"{line}\n", None))
        else:
            content_lines.append(("(none)\n", None))
        
        # Now do a single delete and batch insert (much faster than multiple inserts)
        self.output_text.delete("1.0", tk.END)
        for text, tag in content_lines:
            if tag:
                self.output_text.insert(tk.END, text, tag)
            else:
                self.output_text.insert(tk.END, text)
        
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
            
            # Schedule refresh instead of immediate (non-blocking)
            self._schedule_refresh()
            
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
            """Watcher thread main loop. Simplified: poll every second for countdown."""
            self.watcher = KackyWatcher(
                config=self.config,
                on_status_update=lambda msg: self._queue_status_update(msg),
                on_live_notification=self.on_live_notification,
                on_summary_update=self.on_summary_update,
            )
            # Simplified: poll every second to handle countdown and fetch triggers
            while self.running:
                try:
                    # Check if immediate fetch is requested
                    immediate_fetch = self.immediate_fetch_event.is_set()
                    if immediate_fetch:
                        self.immediate_fetch_event.clear()
                        # Force a fetch when immediate_fetch_event is set
                        self.watcher.poll_once(force_fetch=True)
                    else:
                        self.watcher.poll_once()
                    self.last_fetch_timestamp = time.time()
                    self.last_countdown_update = time.time()  # Reset countdown timer on fetch
                    
                    # Sleep 1 second - poll_once handles countdown internally
                    sleep_interval = 1.0
                    slept = 0.0
                    while slept < sleep_interval and self.running and not self.immediate_fetch_event.is_set():
                        time.sleep(0.1)  # Sleep in small intervals to allow interruption
                        slept += 0.1
                except Exception as e:
                    self._queue_status_update(f"Watcher error: {e}")
                    time.sleep(1)
        
        self.watcher_thread = threading.Thread(target=watcher_loop, daemon=True)
        self.watcher_thread.start()
        
        # Start queue processor to handle updates from watcher thread
        self._start_queue_processor()
        
        self._queue_status_update("Watcher started")
    
    def stop_watcher(self) -> None:
        """Stop the watcher."""
        self.running = False
        if self.watcher_thread:
            self.watcher_thread.join(timeout=2.0)
        self.update_status("Watcher stopped")
    
    def show_settings_dialog(self) -> None:
        """Show settings configuration dialog."""
        settings = load_settings()
        dialog = tk.Toplevel(self.root)
        dialog.title("Settings")
        dialog.geometry("500x300")  # Smaller dialog since we have fewer settings
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        # Variables for settings
        vars_frame = {}
        
        # Create scrollable frame
        canvas = tk.Canvas(dialog)
        scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Settings fields (only user-facing settings)
        row = 0
        
        # Enable Notifications
        ttk.Label(scrollable_frame, text="Enable Notifications:", font=("Arial", 9, "bold")).grid(row=row, column=0, sticky=tk.W, padx=10, pady=5)
        enable_notif_var = tk.BooleanVar(value=settings.get("ENABLE_NOTIFICATIONS", True))
        notif_cb = ttk.Checkbutton(scrollable_frame, variable=enable_notif_var)
        notif_cb.grid(row=row, column=1, sticky=tk.W, padx=10, pady=5)
        if not HAS_NOTIFICATIONS:
            notif_cb.config(state=tk.DISABLED)
            ttk.Label(scrollable_frame, text="(Windows notifications not available)", font=("Arial", 8), foreground="gray").grid(row=row, column=2, sticky=tk.W, padx=5)
        vars_frame["ENABLE_NOTIFICATIONS"] = enable_notif_var
        row += 1
        
        # Log Level (for debugging)
        ttk.Label(scrollable_frame, text="Log Level:", font=("Arial", 9, "bold")).grid(row=row, column=0, sticky=tk.W, padx=10, pady=5)
        log_level_var = tk.StringVar(value=settings.get("LOG_LEVEL", "INFO"))
        log_level_combo = ttk.Combobox(scrollable_frame, textvariable=log_level_var, values=["DEBUG", "INFO", "WARNING", "ERROR"], state="readonly", width=20)
        log_level_combo.grid(row=row, column=1, sticky=tk.W, padx=10, pady=5)
        ttk.Label(scrollable_frame, text="(for troubleshooting)", font=("Arial", 8), foreground="gray").grid(row=row, column=2, sticky=tk.W, padx=5)
        vars_frame["LOG_LEVEL"] = log_level_var
        row += 1
        
        # Buttons
        button_frame = ttk.Frame(scrollable_frame)
        button_frame.grid(row=row, column=0, columnspan=2, pady=20)
        
        def on_save():
            """Save settings and reload config."""
            new_settings = {}
            for key, var in vars_frame.items():
                if isinstance(var, tk.BooleanVar):
                    new_settings[key] = var.get()
                elif isinstance(var, tk.IntVar):
                    new_settings[key] = var.get()
                elif isinstance(var, tk.StringVar):
                    new_settings[key] = var.get()
            
            # Preserve internal settings that are not shown in GUI
            defaults = get_default_settings()
            for key in ["USER_AGENT", "REQUEST_TIMEOUT_SECONDS", "WATCHLIST_REFRESH_SECONDS", "LIVE_DURATION_SECONDS"]:
                if key in defaults:
                    new_settings[key] = settings.get(key, defaults[key])
            
            if save_settings(new_settings):
                # Reload config
                self.config = load_config()
                # Update logging level
                setup_logging(self.config["LOG_LEVEL"])
                
                # Update watcher config if it exists
                if self.watcher:
                    self.watcher.config = self.config
                    # Update live duration in state if it changed
                    if hasattr(self.watcher, 'state') and hasattr(self.watcher.state, 'live_duration_seconds'):
                        self.watcher.state.live_duration_seconds = self.config.get("LIVE_DURATION_SECONDS", 600)
                
                # Notifications are handled via windows_notifications module
                # No instance management needed
                
                messagebox.showinfo("Settings", "Settings saved successfully!\nChanges have been applied immediately.")
                dialog.destroy()
            else:
                messagebox.showerror("Error", "Failed to save settings file.")
        
        def on_reset():
            """Reset to defaults."""
            if messagebox.askyesno("Reset Settings", "Reset all settings to defaults?"):
                defaults = get_default_settings()
                for key, var in vars_frame.items():
                    if key in defaults:
                        if isinstance(var, tk.BooleanVar):
                            var.set(defaults[key])
                        elif isinstance(var, tk.IntVar):
                            var.set(defaults[key])
                        elif isinstance(var, tk.StringVar):
                            var.set(defaults[key])
        
        ttk.Button(button_frame, text="Save", command=on_save).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Reset to Defaults", command=on_reset).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=5)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Focus on dialog
        dialog.focus_set()
    
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
