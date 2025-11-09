"""
Playwright browser installer utility.
Handles checking and installing Playwright browsers for the EXE.
"""
import logging
import os
import subprocess
import sys
from typing import Optional


def _ensure_browsers_path_set() -> None:
    """
    Ensure PLAYWRIGHT_BROWSERS_PATH is set if browsers are installed in system location.
    This helps EXE find browsers installed by system Python.
    MUST be called BEFORE any Playwright imports to ensure Playwright uses the correct path.
    
    This function is safe to call even if logging is not yet configured.
    """
    # Only set if not already set
    if os.getenv("PLAYWRIGHT_BROWSERS_PATH"):
        try:
            logging.debug(f"PLAYWRIGHT_BROWSERS_PATH already set to: {os.getenv('PLAYWRIGHT_BROWSERS_PATH')}")
        except Exception:
            pass  # Logging not configured yet, that's okay
        return
    
    # Check common locations where system Python installs Playwright browsers
    from pathlib import Path
    
    possible_paths = []
    
    # User's AppData (most common on Windows)
    appdata = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
    if appdata:
        possible_paths.append(Path(appdata) / "ms-playwright")
    
    # User's home directory
    home = os.getenv("USERPROFILE") or os.getenv("HOME")
    if home:
        possible_paths.append(Path(home) / ".cache" / "ms-playwright")
        possible_paths.append(Path(home) / ".local" / "share" / "ms-playwright")
    
    # Check if any of these paths contain chromium
    for path in possible_paths:
        if not path.exists():
            try:
                logging.debug(f"Checking browser path (does not exist): {path}")
            except Exception:
                pass
            continue
        
        # Use glob to find any chromium version
        chromium_matches = list(path.glob("chromium-*/chrome-win/chrome.exe"))
        if chromium_matches:
            # Verify the chromium executable actually exists
            for chromium_exe in chromium_matches:
                if chromium_exe.exists() and chromium_exe.is_file():
                    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(path)
                    try:
                        logging.debug(f"Set PLAYWRIGHT_BROWSERS_PATH to: {path} (found browsers at {chromium_exe})")
                    except Exception:
                        pass
                    return
                else:
                    try:
                        logging.debug(f"Chromium executable path exists in glob but file not found: {chromium_exe}")
                    except Exception:
                        pass
    
    try:
        logging.debug("No Playwright browsers found in common locations, PLAYWRIGHT_BROWSERS_PATH not set")
    except Exception:
        pass


# CRITICAL: Set browsers path at module import time if running in EXE mode
# This ensures the path is set BEFORE any Playwright imports in other modules
# (like schedule_fetcher.py which imports Playwright at module level)
# This is safe because _ensure_browsers_path_set() doesn't require logging to be configured
_is_exe = getattr(sys, 'frozen', False)
if _is_exe:
    try:
        _ensure_browsers_path_set()
    except Exception:
        # Silently fail at module import time - we'll call it again later when logging is set up
        # The important thing is we tried to set the path early
        pass


def _find_and_set_installed_browser_path() -> Optional[str]:
    """
    Find where Playwright browsers are actually installed and set PLAYWRIGHT_BROWSERS_PATH.
    This should be called after installation to ensure the path is set correctly.
    
    Returns:
        Path where browsers were found, or None if not found
    """
    from pathlib import Path
    
    # Check common installation locations
    possible_paths = []
    
    # User's AppData (most common on Windows)
    appdata = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
    if appdata:
        possible_paths.append(Path(appdata) / "ms-playwright")
    
    # User's home directory
    home = os.getenv("USERPROFILE") or os.getenv("HOME")
    if home:
        possible_paths.append(Path(home) / ".cache" / "ms-playwright")
        possible_paths.append(Path(home) / ".local" / "share" / "ms-playwright")
    
    # Check each path for chromium
    for path in possible_paths:
        if not path.exists():
            continue
        
        # Look for chromium installation
        chromium_matches = list(path.glob("chromium-*/chrome-win/chrome.exe"))
        for chromium_exe in chromium_matches:
            if chromium_exe.exists() and chromium_exe.is_file():
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(path)
                logging.debug(f"Found installed browsers at: {path} (chromium at {chromium_exe})")
                logging.debug(f"Set PLAYWRIGHT_BROWSERS_PATH to: {path}")
                return str(path)
    
    logging.debug("Could not find installed browser path after installation")
    return None


def check_browsers_installed() -> bool:
    """
    Check if Playwright browsers (specifically Chromium) are installed.
    
    Returns:
        True if browsers are installed, False otherwise
    """
    # CRITICAL: Set browsers path BEFORE importing Playwright
    # Playwright determines browser locations when it's imported, so we must set
    # PLAYWRIGHT_BROWSERS_PATH before any Playwright imports
    try:
        _ensure_browsers_path_set()
        logging.debug(f"After _ensure_browsers_path_set(), PLAYWRIGHT_BROWSERS_PATH={os.getenv('PLAYWRIGHT_BROWSERS_PATH')}")
    except Exception as e:
        logging.debug(f"Could not set browsers path: {e}", exc_info=True)
    
    try:
        # Now import Playwright - it will use the PLAYWRIGHT_BROWSERS_PATH we just set
        from playwright.sync_api import sync_playwright
        logging.debug("Playwright imported, checking browser installation...")
        
        with sync_playwright() as p:
            try:
                # Try to get the browser path - if it exists, browsers are installed
                browser_path = p.chromium.executable_path
                logging.debug(f"Chromium executable path from Playwright: {browser_path}")
                if browser_path and os.path.exists(browser_path):
                    logging.debug(f"Browsers found at: {browser_path}")
                    return True
                else:
                    logging.debug(f"Browser path from Playwright doesn't exist: {browser_path}")
            except Exception as e:
                logging.debug(f"Error getting browser path: {e}", exc_info=True)
                # Try to actually launch to see if it works
                try:
                    logging.debug("Attempting to launch browser to verify installation...")
                    browser = p.chromium.launch(headless=True)
                    browser.close()
                    logging.debug("Browsers are installed (launch test succeeded)")
                    return True
                except Exception as launch_err:
                    logging.debug(f"Browser launch test failed: {launch_err}", exc_info=True)
        return False
    except ImportError:
        logging.debug("Playwright not imported (ImportError)")
        return False
    except Exception as e:
        logging.debug(f"Error checking Playwright browsers: {e}", exc_info=True)
        return False


def install_browsers() -> tuple[bool, Optional[str]]:
    """
    Install Playwright browsers (Chromium).
    
    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    logging.debug("=== install_browsers() called ===")
    logging.debug(f"Current PLAYWRIGHT_BROWSERS_PATH: {os.getenv('PLAYWRIGHT_BROWSERS_PATH')}")
    
    # CRITICAL: Set browsers path BEFORE any Playwright imports or operations
    # This ensures Playwright knows where to look for/install browsers
    try:
        _ensure_browsers_path_set()
        logging.debug(f"After _ensure_browsers_path_set(), PLAYWRIGHT_BROWSERS_PATH: {os.getenv('PLAYWRIGHT_BROWSERS_PATH')}")
    except Exception as e:
        logging.debug(f"Could not ensure browsers path before installation: {e}", exc_info=True)
    
    try:
        # Check if we're running from an EXE (PyInstaller)
        is_exe = getattr(sys, 'frozen', False)
        logging.debug(f"Running in EXE mode: {is_exe}")
        logging.debug(f"sys.executable: {sys.executable}")
        
        if is_exe:
            # In EXE mode, prioritize bundled Playwright's internal API
            # This installs browsers to the location the bundled Playwright expects
            logging.debug("Attempting EXE mode installation (prioritizing bundled Playwright)...")
            
            # First, try using Playwright's bundled CLI (most reliable for EXE)
            logging.debug("Trying bundled Playwright CLI installation (priority method)...")
            try:
                # Import Playwright modules (after setting path)
                import playwright
                from playwright._impl._driver import install_driver
                
                # Install the driver first
                try:
                    driver_path = install_driver()
                    logging.debug(f"Playwright driver installed/verified at: {driver_path}")
                except Exception as e:
                    logging.debug(f"Driver installation check: {e}")
                
                # Try to use Playwright's CLI to install browsers
                try:
                    from playwright._impl._cli import install as cli_install
                    import sys as sys_module
                    original_argv = sys_module.argv[:]
                    try:
                        sys_module.argv = ["playwright", "install", "chromium"]
                        logging.debug("Installing browsers via bundled Playwright CLI...")
                        cli_install()
                        logging.debug("Playwright browsers installed via bundled CLI")
                        
                        # After installation, find where browsers were installed and set path
                        import time
                        time.sleep(2)  # Give installation time to complete
                        browser_path = _find_and_set_installed_browser_path()
                        if browser_path:
                            logging.debug(f"Found and set browser path after installation: {browser_path}")
                        else:
                            logging.warning("Could not automatically detect browser path after installation")
                        
                        # Verify installation
                        if check_browsers_installed():
                            logging.debug("Installation verified - browsers detected and working")
                            return True, None
                        else:
                            logging.warning("Installation completed but browsers not immediately detected - may need restart")
                            # Still return success - browsers are installed, just need to set path on restart
                            return True, None
                    finally:
                        sys_module.argv = original_argv
                except ImportError as cli_import_err:
                    logging.debug(f"CLI module not available: {cli_import_err}, trying alternative methods...")
                    # Fall through to launch method
                except Exception as cli_err:
                    logging.warning(f"CLI install failed: {cli_err}, trying alternative...", exc_info=True)
                    # Fall through to launch method
                
                # Alternative: Try launching browser which triggers installation
                logging.debug("Trying browser launch method (may trigger auto-installation)...")
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    try:
                        browser = p.chromium.launch(headless=True)
                        browser.close()
                        logging.debug("Playwright browsers installed successfully (via launch)")
                        # Find and set browser path after launch-triggered installation
                        browser_path = _find_and_set_installed_browser_path()
                        if browser_path:
                            logging.debug(f"Found and set browser path after launch: {browser_path}")
                        return True, None
                    except Exception as launch_err:
                        error_str = str(launch_err)
                        logging.debug(f"Browser launch failed: {error_str}")
                        # If browsers don't exist, launch will fail - need to install
                        if "Executable doesn't exist" in error_str or "browser" in error_str.lower() or "chromium" in error_str.lower():
                            logging.debug("Browsers not found, need to install via system Python")
                            # Fall through to system Python method
                        else:
                            return False, f"Browser launch failed: {error_str}"
                            
            except ImportError as e:
                logging.warning(f"Playwright import failed: {e}, trying system Python...")
                # Fall through to system Python method
            except Exception as e:
                logging.warning(f"Bundled Playwright installation failed: {e}, trying system Python...")
                # Fall through to system Python method
            
            # Fallback: Use system Python to install browsers
            # Then set environment variable so EXE can find them
            logging.debug("Trying system Python installation...")
            import shutil
            python_exe = None
            for python_cmd in ["python", "python3", "py"]:
                python_exe = shutil.which(python_cmd)
                if python_exe:
                    logging.debug(f"Found Python at: {python_exe}")
                    break
            
            if python_exe:
                # Use subprocess with found Python
                # Try pythonw first (no console window), fallback to python
                pythonw_exe = python_exe.replace("python.exe", "pythonw.exe")
                if os.path.exists(pythonw_exe):
                    python_cmd = pythonw_exe
                    logging.debug(f"Using Pythonw (no console) at {python_cmd} to install browsers...")
                else:
                    python_cmd = python_exe
                    logging.debug(f"Using Python at {python_cmd} to install browsers...")
                
                try:
                    result = subprocess.run(
                        [python_cmd, "-m", "playwright", "install", "chromium"],
                        capture_output=True,
                        text=True,
                        timeout=300,
                        check=False
                    )
                    
                    if result.returncode == 0:
                        logging.debug("Playwright browsers installed successfully via Python subprocess")
                        logging.debug(f"Installation output: {result.stdout}")
                        if result.stderr:
                            logging.debug(f"Installation stderr: {result.stderr}")
                        
                        # After installation, find where browsers were installed and set path
                        import time
                        time.sleep(2)  # Give installation time to complete
                        browser_path = _find_and_set_installed_browser_path()
                        if browser_path:
                            logging.debug(f"Found and set browser path after system Python installation: {browser_path}")
                        else:
                            logging.warning("Could not automatically detect browser path after system Python installation")
                        
                        # Re-check to verify installation
                        if check_browsers_installed():
                            logging.debug("Installation verified - browsers are now detected and working")
                            return True, None
                        else:
                            logging.warning("Installation reported success but browsers not immediately detected - may need restart")
                            # Still return True - browsers are installed, just need to set path on restart
                            return True, None
                    else:
                        error_msg = result.stderr or result.stdout or "Unknown error"
                        logging.error(f"Installation failed: {error_msg}")
                        return False, error_msg
                except subprocess.TimeoutExpired:
                    return False, "Installation timed out after 5 minutes"
                except Exception as e:
                    logging.error(f"Subprocess error: {e}", exc_info=True)
                    return False, str(e)
            
            # Fallback: Try Playwright's internal API
            logging.debug("Python not found, trying Playwright internal API...")
            try:
                import playwright
                from playwright._impl._driver import install_driver
                
                logging.debug("Installing Playwright driver first...")
                try:
                    driver_path = install_driver()
                    logging.debug(f"Playwright driver installed at: {driver_path}")
                except Exception as e:
                    logging.warning(f"Driver installation issue (may already be installed): {e}")
                
                # Try using sync_playwright - launching will trigger browser installation if needed
                logging.debug("Attempting to launch browser to trigger installation...")
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    try:
                        browser = p.chromium.launch(headless=True)
                        browser.close()
                        logging.debug("Playwright browsers installed successfully (via launch)")
                        return True, None
                    except Exception as e:
                        error_str = str(e)
                        logging.error(f"Browser launch failed: {error_str}")
                        if "Executable doesn't exist" in error_str or "browser" in error_str.lower():
                            # Browsers not installed, try CLI install
                            logging.debug("Browsers not found, trying CLI install...")
                            try:
                                from playwright._impl._cli import install as cli_install
                                import sys as sys_module
                                original_argv = sys_module.argv[:]
                                try:
                                    sys_module.argv = ["playwright", "install", "chromium"]
                                    cli_install()
                                    logging.debug("Playwright browsers installed via CLI")
                                    return True, None
                                finally:
                                    sys_module.argv = original_argv
                            except Exception as cli_err:
                                logging.error(f"CLI install failed: {cli_err}", exc_info=True)
                                return False, f"Could not install browsers. Error: {cli_err}. Please install Python and run: python -m playwright install chromium"
                        return False, f"Browser launch failed: {error_str}"
                    
            except ImportError as e:
                logging.error(f"Playwright import failed: {e}")
                return False, f"Playwright module not available: {e}"
            except Exception as e:
                logging.error(f"Unexpected error in EXE mode installation: {e}", exc_info=True)
                return False, f"Installation failed: {e}. Please install Python and run: python -m playwright install chromium"
        else:
            # Regular Python mode - use subprocess
            logging.debug("Installing Playwright browsers (Python mode)...")
            
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    capture_output=True,
                    text=True,
                    timeout=300  # 5 minute timeout
                )
                
                if result.returncode == 0:
                    logging.debug("Playwright browsers installed successfully")
                    logging.debug(f"Installation output: {result.stdout}")
                    return True, None
                else:
                    error_msg = result.stderr or result.stdout or "Unknown error"
                    logging.error(f"Failed to install Playwright browsers: {error_msg}")
                    logging.error(f"Return code: {result.returncode}")
                    return False, error_msg
            except Exception as e:
                logging.error(f"Subprocess error: {e}")
                import traceback
                logging.error(traceback.format_exc())
                return False, str(e)
                
    except subprocess.TimeoutExpired:
        return False, "Installation timed out after 5 minutes"
    except FileNotFoundError:
        return False, "Python interpreter not found. Cannot install Playwright browsers."
    except Exception as e:
        logging.error(f"Error installing Playwright browsers: {e}")
        return False, str(e)


def install_browsers_with_progress(callback: Optional[callable] = None) -> tuple[bool, Optional[str]]:
    """
    Install Playwright browsers with optional progress callback.
    
    Args:
        callback: Optional function to call with progress updates (message: str)
        
    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    if callback:
        callback("Checking Playwright browser installation...")
    
    if check_browsers_installed():
        if callback:
            callback("Playwright browsers already installed")
        return True, None
    
    if callback:
        callback("Installing Playwright browsers (this may take a few minutes)...")
    
    success, error = install_browsers()
    
    if success:
        if callback:
            callback("Playwright browsers installed successfully")
    else:
        if callback:
            callback(f"Failed to install Playwright browsers: {error or 'Unknown error'}")
    
    return success, error

