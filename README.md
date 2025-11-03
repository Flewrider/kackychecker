# Kacky Watcher

A Python application that monitors the [Kacky schedule](https://kacky.gg/schedule) and notifies you when watched maps go live. Available in both GUI and CLI modes.

## Features

- **GUI Mode**: Split-pane interface with editable watchlist and live/tracked output
- **CLI Mode**: Console-based monitoring with detailed output
- **Smart Polling**: Only fetches schedule when maps are near their live time or watchlist changes
- **Live Map Persistence**: Maps stay in "live" status for configurable duration (default 10 minutes)
- **Multiple Server Support**: Tracks maps across multiple servers
- **Headless Browser Fallback**: Optional Playwright support for client-rendered content

## Installation

### Prerequisites

- Python 3.11 or higher
- pip (Python package manager)

### Setup

1. **Clone or download this repository**

2. **Create and activate a virtual environment** (recommended)

   ```powershell
   # Windows (PowerShell)
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   
   # Linux/Mac
   python -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Install Playwright browsers** (optional, for headless browser fallback)

   ```bash
   python -m playwright install
   ```

5. **Create your `.env` file**

   Copy `env.example` to `.env` and adjust values if desired:

   ```powershell
   # Windows (PowerShell)
   Copy-Item -Path env.example -Destination .env -Force
   
   # Linux/Mac
   cp env.example .env
   ```

## Configuration

Edit `.env` to customize behavior:

```env
CHECK_INTERVAL_SECONDS=20          # Base polling interval
REQUEST_TIMEOUT_SECONDS=10          # HTTP request timeout
USER_AGENT=KackyWatcher/1.0 (+https://kacky.gg/schedule)
LOG_LEVEL=INFO                       # DEBUG, INFO, WARNING, ERROR
ENABLE_BROWSER=1                     # 1 to enable Playwright fallback, 0 to disable
WATCHLIST_REFRESH_SECONDS=20        # How often to check for watchlist changes
ETA_FETCH_THRESHOLD_SECONDS=60      # Fetch when ETA is ≤ this many seconds
LIVE_DURATION_SECONDS=600            # How long maps stay "live" after detection (10 minutes)
```

## Usage

### GUI Mode (Default)

Launch the GUI application:

```bash
python main.py
```

Or simply:

```bash
python gui.py
```

**GUI Features:**
- **Left Pane**: Editable watchlist - add/remove map numbers directly
- **Right Pane**: Live and tracked maps display
  - **Live**: Maps currently live with server names and remaining time
  - **Tracked**: Upcoming maps sorted by ETA
- **Status Bar**: Shows current activity and fetch reasons
- **Auto-save**: Watchlist automatically saves 1 second after you stop typing

### CLI Mode

Run in console mode:

```bash
python main.py --cli
```

Or use the original script:

```bash
python kacky_watcher.py
```

**CLI Output:**
- Prints "KACKY MAP LIVE: #<number>" when a watched map goes live
- Displays periodic summary with live and tracked maps
- Shows fetch reasons and timing information

### Watchlist Format

Edit `watchlist.txt` to specify which maps to monitor:

```text
# One map number per line. Lines starting with # are comments.
# Examples:
379
385
391
382
```

In GUI mode, you can edit the watchlist directly in the left pane - changes are saved automatically.

## How It Works

1. **Initial Fetch**: On startup, fetches the schedule to build initial state
2. **Smart Polling**: Only fetches when:
   - A new map is added to the watchlist
   - A tracked map's ETA is within the threshold (default 60 seconds)
   - A live map's persistence window is about to expire
3. **Local Countdown**: Between fetches, ETAs count down locally based on refresh interval
4. **Live Persistence**: Maps stay in "live" status for 10 minutes after detection
5. **Multi-Server Tracking**: Handles maps that are live on one server and upcoming on others

## Project Structure

```
kackychecker/
├── config.py              # Configuration loading
├── schedule_fetcher.py    # HTTP and Playwright fetching
├── schedule_parser.py     # HTML parsing
├── watchlist_manager.py   # Watchlist I/O
├── watcher_state.py       # State management
├── watcher_core.py        # Core polling logic
├── gui.py                 # GUI application
├── main.py                # Entry point (GUI/CLI selector)
├── kacky_watcher.py       # CLI entry point (backwards compatible)
├── watchlist.txt          # Your map watchlist
├── env.example            # Environment variable template
├── requirements.txt       # Python dependencies
├── tests/                 # Unit tests
│   ├── test_config.py
│   ├── test_parser.py
│   ├── test_watchlist.py
│   └── test_state.py
└── README.md              # This file
```

## Running Tests

Install test dependencies (pytest is included in requirements.txt) and run:

```bash
pytest tests/
```

## Troubleshooting

**No maps detected:**
- Check that `watchlist.txt` contains valid map numbers
- Verify the schedule page structure hasn't changed (check logs)
- Enable `ENABLE_BROWSER=1` if the site uses client-side rendering

**GUI not opening:**
- Ensure tkinter is installed (usually included with Python)
- Try CLI mode: `python main.py --cli`

**Frequent fetches:**
- Increase `ETA_FETCH_THRESHOLD_SECONDS` to reduce fetch frequency
- Check that watchlist isn't being edited frequently (auto-save triggers reload)

## Notes

- Source page: https://kacky.gg/schedule
- The parser looks for schedule rows with map numbers (e.g., "379 - ...") and LIVE badges
- Maps are tracked across multiple servers
- Notifications are sent once per map when it first goes live

## License

This project is provided as-is for personal use.

