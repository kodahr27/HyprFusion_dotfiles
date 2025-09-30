import subprocess
import logging
from typing import List, Any, Optional
from gi.repository import GLib
from ignis.services.applications import Application

logger = logging.getLogger("AppLauncher")

class AppLauncher:
    """Shared application launching utilities"""
    
    DEFAULT_TERMINAL_FORMAT = "kitty %command%"
    
    @classmethod
    def launch_app(cls, app: Application, terminal_format: str = None):
        """Launch an application with optional terminal format"""
        if not app:
            logger.warning("Cannot launch: app is None")
            return
        
        try:
            if terminal_format:
                app.launch(terminal_format=terminal_format)
            else:
                app.launch(terminal_format=cls.DEFAULT_TERMINAL_FORMAT)
            logger.debug(f"Launched app: {app.name}")
        except Exception as e:
            logger.error(f"Failed to launch app {app.name}: {e}")
    
    @classmethod
    def launch_app_delayed(cls, app: Application, delay_ms: int = 250, terminal_format: str = None):
        """Launch an application after a delay (useful for UI interactions)"""
        def delayed_launch():
            cls.launch_app(app, terminal_format)
            return False
        
        GLib.timeout_add(delay_ms, delayed_launch)
    
    @classmethod
    def focus_windows(cls, windows: List[Any]):
        """Focus a list of windows using hyprctl"""
        if not windows:
            logger.debug("No windows to focus")
            return
        
        for window in windows:
            try:
                window_id = getattr(window, "id", None) or getattr(window, "address", None)
                if window_id:
                    # Focus the window
                    result = subprocess.run(
                        ["hyprctl", "dispatch", f"focuswindow address:{window_id}"], 
                        capture_output=True, 
                        text=True
                    )
                    if result.returncode == 0:
                        logger.debug(f"Focused window {window_id}")
                    else:
                        logger.warning(f"Failed to focus window {window_id}: {result.stderr}")
                    
                    # Bring to top
                    subprocess.run(
                        ["hyprctl", "dispatch", f"alterzorder top,address:{window_id}"], 
                        capture_output=True, 
                        text=True
                    )
                else:
                    logger.warning(f"Window has no ID or address: {window}")
            except Exception as e:
                logger.error(f"Error focusing window {window}: {e}")
    
    @classmethod
    def focus_or_launch(cls, app: Application, windows: List[Any], terminal_format: str = None):
        """Focus windows if they exist, otherwise launch the app"""
        if windows:
            cls.focus_windows(windows)
        else:
            cls.launch_app(app, terminal_format)
    
    @classmethod
    def launch_app_action(cls, action, delay_ms: int = 250):
        """Launch an application action after a delay"""
        def delayed_action():
            try:
                action.launch()
                logger.debug(f"Launched action: {action.name}")
            except Exception as e:
                logger.error(f"Failed to launch action {action.name}: {e}")
            return False
        
        GLib.timeout_add(delay_ms, delayed_action)