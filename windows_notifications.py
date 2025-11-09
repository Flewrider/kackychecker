"""
Windows notification module using Windows Toast Notification API.
Works in both development and PyInstaller bundles.
"""
import logging
import sys
import threading
import platform
import os

# Try to use Windows Toast Notifications
HAS_NOTIFICATIONS = False
NOTIFICATION_METHOD = None
_NOTIFICATION_INIT_ERROR = None

# Store notification module globally if available
_notification_module = None

if platform.system() == "Windows":
    # Try plyer first in both development and EXE mode
    # It works reliably if properly bundled
    try:
        from plyer import notification as _notification_module
        HAS_NOTIFICATIONS = True
        NOTIFICATION_METHOD = "plyer"
        _is_exe = getattr(sys, 'frozen', False)
        mode = "EXE" if _is_exe else "development"
        logging.debug(f"Using plyer for notifications ({mode} mode)")
    except (ImportError, Exception) as e:
        _NOTIFICATION_INIT_ERROR = str(e)
        logging.debug(f"Plyer not available: {e}, trying Windows API fallback...")
        # Fallback to Windows API (MessageBox - most reliable fallback)
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            HAS_NOTIFICATIONS = True
            NOTIFICATION_METHOD = "winapi_msgbox"
            logging.debug("Using Windows MessageBox API for notifications (fallback)")
        except (ImportError, OSError, AttributeError) as e2:
            HAS_NOTIFICATIONS = False
            NOTIFICATION_METHOD = None
            _NOTIFICATION_INIT_ERROR = f"{_NOTIFICATION_INIT_ERROR}; {e2}"
            logging.debug(f"Windows API also not available: {e2}")
else:
    HAS_NOTIFICATIONS = False
    NOTIFICATION_METHOD = None
    logging.debug("Not running on Windows, notifications not available")


def show_notification(title: str, message: str, duration: int = 5) -> bool:
    """
    Show a Windows notification.
    Uses Toast Notifications on Windows 10+ if available, falls back to MessageBox.
    
    Args:
        title: Notification title
        message: Notification message
        duration: Duration in seconds (not used for MessageBox, but kept for API compatibility)
    
    Returns:
        True if notification was shown, False otherwise
    """
    if not HAS_NOTIFICATIONS:
        if _NOTIFICATION_INIT_ERROR:
            logging.debug(f"Windows notifications not available: {_NOTIFICATION_INIT_ERROR}")
        else:
            logging.debug("Windows notifications not available")
        return False
    
    try:
        # Use a local variable to track which method to use (can change during execution)
        method = NOTIFICATION_METHOD
        
        if method == "plyer":
            # Use plyer (works in both development and EXE mode if properly bundled)
            try:
                if _notification_module is None:
                    raise ImportError("Plyer notification module not available")
                _notification_module.notify(
                    title=title,
                    message=message,
                    timeout=duration,
                    app_name="Kacky Watcher"
                )
                logging.debug(f"Notification shown via plyer: {title}")
                return True
            except Exception as e:
                logging.warning(f"Plyer notification failed: {e}, trying MessageBox fallback", exc_info=True)
                # Fall through to MessageBox fallback
                method = "winapi_msgbox"
            
        if method == "winapi_msgbox":
            # Use Windows MessageBox API (most reliable, but blocking)
            try:
                import ctypes
                from ctypes import wintypes
                
                MB_ICONINFORMATION = 0x00000040
                MB_SETFOREGROUND = 0x00010000
                MB_TOPMOST = 0x00040000
                MB_TASKMODAL = 0x00002000  # Task modal - doesn't block other windows as much
                flags = MB_ICONINFORMATION | MB_SETFOREGROUND | MB_TOPMOST | MB_TASKMODAL
                
                user32 = ctypes.windll.user32
                # MessageBox is blocking, but it's better than nothing
                result = user32.MessageBoxW(None, message, title, flags)
                logging.debug(f"Notification shown via MessageBox: {title}, result={result}")
                return result != 0
            except Exception as e:
                logging.error(f"MessageBox notification failed: {e}", exc_info=True)
                return False
        else:
            logging.debug(f"No valid notification method (method: {method})")
            return False
            
    except Exception as e:
        logging.error(f"Failed to show notification: {e}", exc_info=True)
        # Try to log the initialization error if available
        if _NOTIFICATION_INIT_ERROR:
            logging.error(f"Notification initialization error was: {_NOTIFICATION_INIT_ERROR}")
        return False


def show_notification_async(title: str, message: str, duration: int = 5) -> None:
    """
    Show a Windows notification asynchronously in a separate thread.
    
    Args:
        title: Notification title
        message: Notification message
        duration: Duration in seconds
    """
    def _show():
        try:
            show_notification(title, message, duration)
        except Exception as e:
            logging.error(f"Error in notification thread: {e}", exc_info=True)
    
    thread = threading.Thread(target=_show, daemon=True, name="NotificationThread")
    thread.start()

