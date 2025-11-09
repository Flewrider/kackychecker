# Kacky Watcher

A Windows desktop application that monitors the [Kacky schedule](https://kacky.gg/schedule) and notifies you when your watched maps go live. Built with Python and Tkinter, packaged as a standalone EXE.

## Features

- **Real-time Monitoring**: Tracks map schedules across multiple servers
- **Desktop Notifications**: Windows toast notifications when watched maps go live
- **Smart Polling**: Efficient fetching with local countdown - only syncs times when needed
- **Multiple Server Support**: Tracks maps across all servers simultaneously
- **Persistent State**: Remembers your watched maps and settings between sessions
- **No Terminal Required**: Windowed application (EXE) runs without a console window

## Download & Installation

### Pre-built EXE (Recommended)

1. **Download from GitHub Releases**
   - Go to [Releases](https://github.com/flewrider/kackychecker/releases)
   - Download the latest `KackyWatcher.zip`
   - Extract the zip file
   - Run `KackyWatcher.exe`

2. **First Run Setup**
   - On first launch, the app will prompt you to install Playwright browsers (required)
   - Click "Yes" to install (downloads ~100-200MB, takes a few minutes)
   - The app cannot function without Playwright browsers

3. **Configuration Files**
   - `settings.json` - Application settings (created automatically)
   - `watchlist.txt` - List of maps to track (created automatically)
   - `map_status.json` - Tracking state (created automatically)
   - `log.txt` - Application logs (created automatically)
   
   All files are created in the same folder as `KackyWatcher.exe` on first run.

### Requirements

- **Windows 10 or later**
- **Playwright browsers** (installed automatically on first run)
- **No Python installation required** (EXE includes everything)

## Usage

### Adding Maps to Watchlist

1. Launch `KackyWatcher.exe`
2. In the left pane, check the boxes next to map numbers you want to track
3. Maps are automatically saved to `watchlist.txt`
4. Uncheck boxes to remove maps from the watchlist

### Understanding the Display

**Live Maps:**
- Maps currently live on any server
- Shows server name and remaining time
- Notifications are sent when a map first goes live

**Tracked Maps:**
- Upcoming maps with ETA (estimated time until live)
- Sorted by earliest ETA
- Shows which server the map will be on

**Status Bar:**
- Shows current activity (fetching, idle, etc.)
- Displays warnings if website is unreachable

### Settings

Access settings via `Settings > Configure...` in the menu:

- **Enable Notifications**: Toggle desktop notifications (Windows toast)
- **Log Level**: Set logging level (DEBUG, INFO, WARNING, ERROR)
  - Use DEBUG for troubleshooting
  - INFO is recommended for normal use

## How It Works

The application uses a smart polling system that minimizes website requests:

1. **Initial Fetch**: Fetches schedule on startup to get current state
2. **Local Countdown**: ETAs and live times count down locally every second
3. **State Transitions**: Tracked maps automatically become live when ETA hits 0
4. **Time Syncing**: Fetches only when:
   - New maps are added to watchlist (no data available)
   - Live maps need resync (1 minute after going live)
   - Periodic refetch (every 60s for unknown time maps, or 5 minutes for staleness prevention)
5. **Live Persistence**: Maps stay "live" until their time expires, then check if they're live again

### Key Features

- **No unnecessary fetches**: State transitions (tracked → live) happen locally
- **Efficient**: Only fetches to sync times with the server
- **Resilient**: Handles network issues and website transitions gracefully
- **Fast**: Local countdown provides instant updates without waiting for website

## Developer Documentation

> **Note**: The EXE version only supports GUI mode. CLI mode is available when running from source.

### Prerequisites

- **Python 3.11 or higher**
- **pip** (Python package manager)
- **Git** (for cloning the repository)

### Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/flewrider/kackychecker.git
   cd kackychecker
   ```

2. **Create a virtual environment** (recommended)
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

4. **Install Playwright browsers**
   ```bash
   python -m playwright install chromium
   ```

5. **Run the application**
   ```bash
   # GUI mode (default)
   python main.py
   
   # CLI mode (optional)
   python main.py --cli
   ```

### Project Structure

```
kackychecker/
├── main.py                 # Entry point (GUI application)
├── gui.py                  # GUI application (Tkinter)
├── watcher_core.py         # Core polling logic
├── watcher_state.py        # State management (ETAs, live maps)
├── schedule_fetcher.py     # HTTP and Playwright fetching
├── schedule_parser.py      # HTML parsing (BeautifulSoup)
├── settings_manager.py     # Settings loading/saving
├── map_status_manager.py   # Map status persistence
├── watchlist_manager.py    # Watchlist I/O
├── path_utils.py           # Path utilities (EXE vs dev mode)
├── playwright_installer.py # Playwright browser installation
├── config.py               # Configuration and logging setup
├── requirements.txt        # Python dependencies
├── kacky_watcher.spec     # PyInstaller spec file
├── build_exe.py           # Local build script
├── .github/
│   └── workflows/
│       └── build-release.yml  # GitHub Actions CI/CD
├── tests/                  # Unit tests
│   ├── test_config.py
│   ├── test_parser.py
│   ├── test_state.py
│   └── test_watchlist.py
└── README.md              # This file
```

### Building the EXE Locally

1. **Install PyInstaller**
   ```bash
   pip install pyinstaller
   ```

2. **Build the EXE**
   ```bash
   python build_exe.py
   ```
   
   Or manually:
   ```bash
   pyinstaller kacky_watcher.spec --clean --noconfirm
   ```

3. **Output**
   - EXE will be in `dist/KackyWatcher.exe`
   - All dependencies are bundled in the EXE

### Running Tests

```bash
pytest tests/
```

### Configuration Files (Development)

When running in development mode, configuration files are created in the project directory:

- `settings.json` - Application settings
- `watchlist.txt` - Map watchlist
- `map_status.json` - Tracking state
- `log.txt` - Application logs

### Internal Settings

The following settings are internal and not shown in the GUI (have sensible defaults):

- `REQUEST_TIMEOUT_SECONDS`: Network timeout (default: 10 seconds)
- `USER_AGENT`: HTTP user agent string
- `WATCHLIST_REFRESH_SECONDS`: How often to check for watchlist changes (default: 20 seconds)
- `LIVE_DURATION_SECONDS`: Fallback duration when time not available from website (default: 600 seconds)

These can be modified in `settings.json` if needed for debugging, but are not exposed in the GUI.

### Code Architecture

**State Management:**
- `WatcherState`: Manages ETAs, live windows, and notification state
- Local countdown handles state transitions (tracked → live)
- Fetches only sync times, never change state

**Fetching:**
- `schedule_fetcher.py`: Handles HTTP and Playwright browser fetching
- Always uses Playwright first (required for JavaScript-rendered content)
- Falls back to HTTP if Playwright fails (usually won't work)

**Parsing:**
- `schedule_parser.py`: Parses HTML table structure
- Extracts server numbers, live maps, upcoming maps, and times
- Handles transitions (empty time cells) gracefully

**GUI:**
- `gui.py`: Tkinter-based GUI
- Threaded watcher loop (prevents GUI freezing)
- Queue-based updates (thread-safe GUI updates)

### Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Troubleshooting

**Playwright browsers not found:**
- The app will prompt to install on first run
- If installation fails, try running manually: `python -m playwright install chromium`
- Check that you have internet connection (browsers are downloaded)

**Maps not showing:**
- Check that maps are in your watchlist (left pane in GUI)
- Verify the website structure hasn't changed (check `log.txt`)
- Enable DEBUG log level in settings to see detailed logs

**Notifications not working:**
- Ensure `ENABLE_NOTIFICATIONS` is enabled in settings
- Check that Windows notifications are enabled for the app
- Verify `win10toast` is installed (included in EXE)

**Website unreachable:**
- Check your internet connection
- Verify https://kacky.gg/schedule is accessible in your browser
- Check `log.txt` for detailed error messages

## Technical Details

### Dependencies

- **tkinter**: GUI framework (included with Python)
- **requests**: HTTP requests (fallback)
- **beautifulsoup4**: HTML parsing
- **playwright**: Headless browser (required for JavaScript rendering)
- **win10toast**: Windows desktop notifications

### Browser Requirements

The application requires Playwright browsers to function:
- **Chromium** browser (~100-200MB download)
- Installed automatically on first run
- Stored in user's AppData directory (system-wide)
- Required because the website uses JavaScript rendering

### Data Files

All user data files are stored in the same directory as the EXE:

- `settings.json`: User settings (notifications, log level)
- `watchlist.txt`: List of tracked maps
- `map_status.json`: Tracking state (which maps are tracked/finished)
- `log.txt`: Application logs (reset on each startup)

## License

This project is provided as-is for personal use.

## Acknowledgments

- Built for the [Kacky](https://kacky.gg) community
- Schedule data from https://kacky.gg/schedule
