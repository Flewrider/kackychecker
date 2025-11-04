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
    """
    # Only set if not already set
    if os.getenv("PLAYWRIGHT_BROWSERS_PATH"):
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
        chromium_path = path / "chromium-*" / "chrome-win" / "chrome.exe"
        # Use glob to find any chromium version
        chromium_matches = list(path.glob("chromium-*/chrome-win/chrome.exe"))
        if chromium_matches:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(path)
            logging.debug(f"Set PLAYWRIGHT_BROWSERS_PATH to: {path} (found browsers)")
            return


def check_browsers_installed() -> bool:
    """
    Check if Playwright browsers (specifically Chromium) are installed.
    
    Returns:
        True if browsers are installed, False otherwise
    """
    # First, try to set the browsers path if needed (for EXE mode)
    try:
        _ensure_browsers_path_set()
    except Exception as e:
        logging.debug(f"Could not set browsers path: {e}")
    
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                # Try to get the browser path - if it exists, browsers are installed
                browser_path = p.chromium.executable_path
                logging.debug(f"Chromium executable path: {browser_path}")
                if browser_path and os.path.exists(browser_path):
                    logging.debug(f"Browsers found at: {browser_path}")
                    return True
                else:
                    logging.debug(f"Browser path doesn't exist: {browser_path}")
            except Exception as e:
                logging.debug(f"Error getting browser path: {e}")
                # Try to actually launch to see if it works
                try:
                    browser = p.chromium.launch(headless=True)
                    browser.close()
                    logging.debug("Browsers are installed (launch test succeeded)")
                    return True
                except Exception as launch_err:
                    logging.debug(f"Browser launch test failed: {launch_err}")
        return False
    except ImportError:
        logging.debug("Playwright not imported")
        return False
    except Exception as e:
        logging.debug(f"Error checking Playwright browsers: {e}")
        return False


def install_browsers() -> tuple[bool, Optional[str]]:
    """
    Install Playwright browsers (Chromium).
    
    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    logging.debug("=== install_browsers() called ===")
    try:
        # Check if we're running from an EXE (PyInstaller)
        is_exe = getattr(sys, 'frozen', False)
        logging.debug(f"Running in EXE mode: {is_exe}")
        logging.debug(f"sys.executable: {sys.executable}")
        
        if is_exe:
            # In EXE mode, try to use bundled Playwright's internal API first
            # This installs browsers to the location the EXE expects
            logging.debug("Attempting EXE mode installation...")
            
            # First, try using Playwright's internal API (bundled in EXE)
            logging.debug("Trying Playwright internal API first...")
            try:
                import playwright
                from playwright._impl._driver import install_driver
                
                # Install the driver first
                try:
                    driver_path = install_driver()
                    logging.debug(f"Playwright driver installed at: {driver_path}")
                except Exception as e:
                    logging.debug(f"Driver already installed or error: {e}")
                
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
                        
                        # Verify installation
                        import time
                        time.sleep(1)
                        if check_browsers_installed():
                            logging.debug("Installation verified - browsers detected")
                            return True, None
                        else:
                            logging.warning("Installation completed but browsers not immediately detected")
                            return True, None  # Still return success, may need restart
                    finally:
                        sys_module.argv = original_argv
                except ImportError as cli_import_err:
                    logging.debug(f"CLI module not available: {cli_import_err}")
                    # Fall through to launch method
                except Exception as cli_err:
                    logging.warning(f"CLI install failed: {cli_err}, trying alternative...")
                    # Fall through to launch method
                
                # Alternative: Try launching browser which triggers installation
                logging.debug("Trying browser launch method...")
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    try:
                        browser = p.chromium.launch(headless=True)
                        browser.close()
                        logging.debug("Playwright browsers installed successfully (via launch)")
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
                        logging.debug(f"Output: {result.stdout}")
                        
                        # Try to find where system Python installed browsers and set env var
                        # This helps the EXE find them
                        try:
                            from pathlib import Path
                            # Playwright installs to user's AppData by default
                            appdata = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
                            if appdata:
                                playwright_cache = Path(appdata) / "ms-playwright"
                                if playwright_cache.exists():
                                    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(playwright_cache)
                                    logging.debug(f"Set PLAYWRIGHT_BROWSERS_PATH to: {playwright_cache}")
                        except Exception as env_err:
                            logging.debug(f"Could not set environment variable: {env_err}")
                        
                        # Re-check to verify installation
                        import time
                        time.sleep(2)  # Give it more time to finish
                        if check_browsers_installed():
                            logging.debug("Installation verified - browsers are now detected")
                            return True, None
                        else:
                            logging.warning("Installation reported success but browsers not detected yet")
                            # Still return True - may need restart or env var
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

