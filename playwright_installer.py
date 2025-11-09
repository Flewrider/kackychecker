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


def _create_browser_version_symlink(expected_version: str) -> bool:
    """
    Create a symlink/junction from an installed Chromium version to the expected version.
    This is needed when system Python installs a different version than what the bundled Playwright expects.
    
    Args:
        expected_version: The Chromium version that the bundled Playwright expects (e.g., "1134")
    
    Returns:
        True if symlink was created or already exists, False otherwise
    """
    from pathlib import Path
    import time
    
    # Find the ms-playwright directory
    appdata = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
    if not appdata:
        logging.debug("Could not find AppData directory for symlink creation")
        return False
    
    ms_playwright_path = Path(appdata) / "ms-playwright"
    if not ms_playwright_path.exists():
        logging.debug(f"ms-playwright directory does not exist: {ms_playwright_path}")
        return False
    
    expected_dir = ms_playwright_path / f"chromium-{expected_version}"
    if expected_dir.exists():
        # Check if it's already the right version or a valid symlink
        if expected_dir.is_symlink() or (expected_dir / "chrome-win" / "chrome.exe").exists():
            logging.debug(f"Expected version directory already exists: {expected_dir}")
            return True
    
    # Wait a bit for installation to complete
    time.sleep(2)
    
    # Find any installed Chromium version
    chromium_dirs = [d for d in ms_playwright_path.iterdir() 
                     if d.is_dir() and d.name.startswith("chromium-") and d.name != f"chromium-{expected_version}"]
    
    if not chromium_dirs:
        logging.debug("No Chromium installation found to create symlink from")
        return False
    
    # Use the first (most recent) installed version
    installed_dir = chromium_dirs[0]
    logging.debug(f"Found installed Chromium at: {installed_dir.name}, creating symlink to chromium-{expected_version}")
    
    try:
        # On Windows, create a directory junction (symlink)
        # Use mklink command via subprocess (junctions work without admin privileges)
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(expected_dir), str(installed_dir)],
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode == 0:
            logging.debug(f"Created junction: {expected_dir} -> {installed_dir}")
            return True
        elif "already exists" in result.stdout or "already exists" in result.stderr:
            logging.debug(f"Junction already exists: {expected_dir}")
            return True
        else:
            logging.warning(f"Failed to create junction via mklink: {result.stderr or result.stdout}")
            # Try alternative: copy the directory structure (as fallback)
            # This is less ideal but works without admin privileges
            logging.debug("Attempting to copy browser files as fallback...")
            try:
                import shutil
                if installed_dir.exists() and not expected_dir.exists():
                    shutil.copytree(installed_dir, expected_dir, dirs_exist_ok=True)
                    logging.debug(f"Copied browser directory: {installed_dir.name} -> chromium-{expected_version}")
                    return True
            except Exception as copy_err:
                logging.warning(f"Failed to copy browser directory: {copy_err}")
            return False
    except Exception as e:
        logging.debug(f"Error creating symlink/junction: {e}", exc_info=True)
        return False


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
            logging.debug(f"Browser path does not exist: {path}")
            continue
        
        # Look for chromium installation - check all versions
        chromium_matches = list(path.glob("chromium-*/chrome-win/chrome.exe"))
        logging.debug(f"Found {len(chromium_matches)} chromium installations in {path}")
        
        for chromium_exe in chromium_matches:
            if chromium_exe.exists() and chromium_exe.is_file():
                # Found a valid chromium installation
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(path)
                logging.debug(f"Found installed browsers at: {path} (chromium at {chromium_exe})")
                logging.debug(f"Set PLAYWRIGHT_BROWSERS_PATH to: {path}")
                
                # Verify the path is actually set
                if os.getenv("PLAYWRIGHT_BROWSERS_PATH") == str(path):
                    logging.debug(f"PLAYWRIGHT_BROWSERS_PATH verified: {os.getenv('PLAYWRIGHT_BROWSERS_PATH')}")
                    return str(path)
                else:
                    logging.warning(f"Failed to set PLAYWRIGHT_BROWSERS_PATH (expected {path}, got {os.getenv('PLAYWRIGHT_BROWSERS_PATH')})")
            else:
                logging.debug(f"Chromium executable path found in glob but file missing: {chromium_exe}")
    
    logging.debug("Could not find installed browser path after installation")
    logging.debug(f"Checked paths: {[str(p) for p in possible_paths]}")
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
                if browser_path:
                    if os.path.exists(browser_path):
                        logging.debug(f"Browsers found at: {browser_path}")
                        return True
                    else:
                        # Browser path is specified but doesn't exist
                        # Extract version from path if possible (e.g., chromium-1134)
                        import re
                        version_match = re.search(r'chromium-(\d+)', browser_path)
                        if version_match:
                            expected_version = version_match.group(1)
                            logging.debug(f"Playwright expects chromium-{expected_version} but it doesn't exist at {browser_path}")
                            logging.debug(f"PLAYWRIGHT_BROWSERS_PATH={os.getenv('PLAYWRIGHT_BROWSERS_PATH')}")
                        else:
                            logging.debug(f"Browser path from Playwright doesn't exist: {browser_path}")
                else:
                    logging.debug("Playwright did not return a browser path")
            except Exception as e:
                logging.debug(f"Error getting browser path: {e}", exc_info=True)
                # Try to actually launch to see if it works (this might trigger installation or give a better error)
                try:
                    logging.debug("Attempting to launch browser to verify installation...")
                    browser = p.chromium.launch(headless=True)
                    browser.close()
                    logging.debug("Browsers are installed (launch test succeeded)")
                    return True
                except Exception as launch_err:
                    error_str = str(launch_err)
                    logging.debug(f"Browser launch test failed: {error_str}")
                    # Check if error mentions a specific version
                    import re
                    version_match = re.search(r'chromium-(\d+)', error_str)
                    if version_match:
                        expected_version = version_match.group(1)
                        logging.debug(f"Playwright expects chromium-{expected_version} but it's not installed")
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
            # In EXE mode, try to use bundled Playwright's installation first
            # This ensures we install the browser version that matches the bundled Playwright
            logging.debug("Attempting EXE mode installation...")
            
            # First, try using the bundled Playwright's CLI to install browsers
            # This should install the version that matches the bundled Playwright
            bundled_cli_success = False
            try:
                from playwright._impl._cli import install as cli_install
                import sys as sys_module
                original_argv = sys_module.argv[:]
                try:
                    sys_module.argv = ["playwright", "install", "chromium"]
                    logging.debug("Installing browsers via bundled Playwright CLI (ensures correct version)...")
                    cli_install()
                    logging.debug("Playwright browsers installed via bundled CLI")
                    bundled_cli_success = True
                except Exception as cli_err:
                    logging.debug(f"Bundled CLI installation failed: {cli_err}, trying system Python...")
                finally:
                    sys_module.argv = original_argv
            except ImportError:
                logging.debug("Bundled Playwright CLI not available, using system Python...")
            
            # If bundled CLI failed or is not available, detect expected version and install it
            if not bundled_cli_success:
                # First, check what version the bundled Playwright expects
                expected_version = None
                try:
                    from playwright.sync_api import sync_playwright
                    with sync_playwright() as p:
                        browser_path = p.chromium.executable_path
                        if browser_path:
                            import re
                            version_match = re.search(r'chromium-(\d+)', browser_path)
                            if version_match:
                                expected_version = version_match.group(1)
                                logging.debug(f"Bundled Playwright expects chromium-{expected_version}")
                except Exception as e:
                    logging.debug(f"Could not determine expected version: {e}")
                
                # Find system Python - prefer pythonw.exe to avoid console window
                import shutil
                python_exe = None
                pythonw_exe = None
                
                # First, try to find pythonw.exe directly in PATH (no console window)
                for pythonw_cmd in ["pythonw", "pythonw3"]:
                    pythonw_exe = shutil.which(pythonw_cmd)
                    if pythonw_exe:
                        logging.debug(f"Found Pythonw in PATH at: {pythonw_exe}")
                        break
                
                # If pythonw not found in PATH, find python.exe and look for pythonw.exe in same directory
                if not pythonw_exe:
                    for python_cmd in ["python", "python3", "py"]:
                        python_exe = shutil.which(python_cmd)
                        if python_exe:
                            logging.debug(f"Found Python at: {python_exe}")
                            # Try to find pythonw.exe in the same directory
                            python_dir = os.path.dirname(python_exe)
                            pythonw_path = os.path.join(python_dir, "pythonw.exe")
                            if os.path.exists(pythonw_path):
                                pythonw_exe = pythonw_path
                                logging.debug(f"Found Pythonw in same directory at: {pythonw_exe}")
                            break
                
                if not python_exe and not pythonw_exe:
                    logging.error("System Python not found. Cannot install Playwright browsers.")
                    return False, "Python is required to install Playwright browsers. Please install Python and run: python -m playwright install chromium"
                
                # Prefer pythonw to avoid console window, fall back to python if not available
                python_cmd = pythonw_exe if pythonw_exe else python_exe
                if pythonw_exe:
                    logging.debug(f"Installing browsers via Pythonw (no console window) at {python_cmd}...")
                else:
                    logging.warning(f"Pythonw not found - using Python (console window will appear) at {python_cmd}...")
                    logging.debug("Note: Install pythonw.exe to avoid console window during browser installation")
                
                try:
                    # Install browsers using system Python's Playwright
                    # This will install browsers to the standard location (AppData\Local\ms-playwright)
                    result = subprocess.run(
                        [python_cmd, "-m", "playwright", "install", "chromium"],
                        capture_output=True,
                        text=True,
                        timeout=600,  # 10 minute timeout (browser download can be slow)
                        check=False
                    )
                    
                    if result.returncode != 0:
                        error_msg = result.stderr or result.stdout or "Unknown error"
                        logging.error(f"Installation failed with return code {result.returncode}")
                        logging.error(f"Installation error: {error_msg[:1000]}")
                        return False, f"Installation failed: {error_msg[:200]}"
                    
                    logging.debug("Playwright browsers installed successfully via Python subprocess")
                    logging.debug(f"Installation stdout: {result.stdout[:500]}")
                    if result.stderr:
                        logging.debug(f"Installation stderr: {result.stderr[:500]}")
                    
                    # If we know the expected version and it's different from what was installed,
                    # create a symlink/junction to make the installed version available as the expected version
                    if expected_version:
                        import time
                        time.sleep(3)  # Wait for installation to complete
                        symlink_created = _create_browser_version_symlink(expected_version)
                        if symlink_created:
                            logging.debug(f"Successfully created symlink/junction for chromium-{expected_version}")
                        else:
                            logging.warning(f"Failed to create symlink for chromium-{expected_version} - browser may not work correctly")
                        
                except subprocess.TimeoutExpired:
                    return False, "Installation timed out after 10 minutes. Please try installing manually: python -m playwright install chromium"
                except Exception as e:
                    logging.error(f"Subprocess error: {e}", exc_info=True)
                    return False, f"Installation error: {str(e)}"
            
            # After installation (either method), set up paths and verify
            import time
            time.sleep(5)  # Give installation time to fully complete and write files
            
            # Force refresh the path detection - this sets PLAYWRIGHT_BROWSERS_PATH
            browser_path = _find_and_set_installed_browser_path()
            if browser_path:
                logging.debug(f"Found and set browser path after installation: {browser_path}")
                current_path = os.getenv("PLAYWRIGHT_BROWSERS_PATH")
                logging.debug(f"PLAYWRIGHT_BROWSERS_PATH is now: {current_path}")
            else:
                logging.warning("Could not automatically detect browser path after installation")
                # Try again after a longer wait
                time.sleep(3)
                browser_path = _find_and_set_installed_browser_path()
                if browser_path:
                    logging.debug(f"Found browser path on second attempt: {browser_path}")
                else:
                    # Last attempt - check if ms-playwright directory exists at all
                    appdata = os.getenv("LOCALAPPDATA")
                    if appdata:
                        ms_playwright_path = os.path.join(appdata, "ms-playwright")
                        if os.path.exists(ms_playwright_path):
                            logging.debug(f"ms-playwright directory exists at {ms_playwright_path}, setting path...")
                            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = ms_playwright_path
                            browser_path = ms_playwright_path
            
            # Force a fresh path check before verifying
            _ensure_browsers_path_set()
            
            # Check if we need to create a symlink for version mismatch
            # This handles the case where expected_version wasn't detected before installation
            # OR if we need to create a symlink after installation completes
            if not bundled_cli_success:
                try:
                    from playwright.sync_api import sync_playwright
                    with sync_playwright() as p:
                        browser_path_check = p.chromium.executable_path
                        if browser_path_check:
                            import re
                            version_match = re.search(r'chromium-(\d+)', browser_path_check)
                            if version_match:
                                detected_expected_version = version_match.group(1)
                                # Always create symlink if we detect an expected version
                                # (either we didn't detect it before, or we need to ensure it exists)
                                if not expected_version or detected_expected_version != expected_version:
                                    expected_version = detected_expected_version
                                    logging.debug(f"Detected expected version after installation: chromium-{expected_version}")
                                    # Create symlink if needed (this will check if it already exists)
                                    symlink_created = _create_browser_version_symlink(expected_version)
                                    if symlink_created:
                                        logging.debug(f"Created/verified symlink for chromium-{expected_version} after installation")
                                    else:
                                        logging.warning(f"Failed to create symlink for chromium-{expected_version}")
                except Exception as e:
                    logging.debug(f"Could not check expected version after installation: {e}", exc_info=True)
            
            # Verify installation
            if check_browsers_installed():
                logging.debug("Installation verified - browsers are detected and working")
                return True, None
            else:
                logging.warning("Installation completed but browsers not immediately detected")
                logging.debug("Browsers are installed - they will be detected on next restart")
                logging.debug(f"PLAYWRIGHT_BROWSERS_PATH={os.getenv('PLAYWRIGHT_BROWSERS_PATH')}")
                # Return success - browsers are installed, path is set, they'll work on restart
                return True, None
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

