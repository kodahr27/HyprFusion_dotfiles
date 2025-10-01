import subprocess
import logging
from typing import List, Any, Optional, Callable
from gi.repository import GLib
from ignis.services.applications import Application
from ignis.menu_model import IgnisMenuModel, IgnisMenuItem, IgnisMenuSeparator

logger = logging.getLogger("TaskbarUtils")

class TaskbarUtils:
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
    def close_windows(cls, windows: List[Any]):
        """Close a list of windows using hyprctl"""
        if not windows:
            logger.debug("No windows to close")
            return
        
        for window in windows:
            try:
                window_id = getattr(window, "id", None) or getattr(window, "address", None)
                if window_id:
                    result = subprocess.run(
                        ["hyprctl", "dispatch", f"closewindow address:{window_id}"],
                        capture_output=True,
                        text=True
                    )
                    if result.returncode == 0:
                        logger.debug(f"Closed window {window_id}")
                    else:
                        logger.warning(f"Failed to close window {window_id}: {result.stderr}")
                else:
                    logger.warning(f"Window has no ID or address: {window}")
            except Exception as e:
                logger.error(f"Error closing window {window}: {e}")
    
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
    
    @classmethod
    def build_app_context_menu(cls, app: Application, window_count: int, windows: List[Any], 
                               on_focus_callback: Optional[Callable] = None,
                               on_close_callback: Optional[Callable] = None,
                               show_launch: bool = False) -> IgnisMenuModel:
        """
        Build a standard context menu for an application with windows.
        
        Args:
            app: The application
            window_count: Number of windows open for this app
            windows: List of window objects
            on_focus_callback: Optional custom focus callback (defaults to focus_or_launch)
            on_close_callback: Optional custom close callback (defaults to close_windows)
            show_launch: If True, shows "Launch" instead of "Focus" when windows exist
            
        Returns:
            IgnisMenuModel ready to be used in a PopoverMenu
        """
        if on_focus_callback is None:
            on_focus_callback = lambda: cls.focus_or_launch(app, windows)
        
        if on_close_callback is None:
            on_close_callback = lambda: cls.close_windows(windows)
        
        menu_items = []
        
        # Add Launch or Focus option
        if window_count == 0:
            # No windows open - always show Launch
            menu_items.append(
                IgnisMenuItem(
                    label="Launch",
                    on_activate=lambda x: GLib.idle_add(cls.launch_app, app)
                )
            )
        elif show_launch:
            # Windows exist but we want to show Launch anyway (pinned apps)
            menu_items.append(
                IgnisMenuItem(
                    label="Launch",
                    on_activate=lambda x: GLib.idle_add(cls.launch_app, app)
                )
            )
        else:
            # Windows exist and we want to show Focus (running apps)
            menu_items.append(
                IgnisMenuItem(
                    label="Focus All" if window_count > 1 else "Focus",
                    on_activate=lambda x: GLib.idle_add(on_focus_callback)
                )
            )
        
        menu_items.append(IgnisMenuSeparator())
        
        # Add New Window only if windows exist
        if window_count > 0:
            menu_items.append(
                IgnisMenuItem(
                    label="New Window",
                    on_activate=lambda x: GLib.idle_add(cls.launch_app, app)
                )
            )
            menu_items.append(IgnisMenuSeparator())
        
        # Add close option(s)
        if window_count > 1:
            menu_items.append(
                IgnisMenuItem(
                    label="Close All",
                    on_activate=lambda x: GLib.idle_add(on_close_callback)
                )
            )
        elif window_count == 1:
            menu_items.append(
                IgnisMenuItem(
                    label="Close",
                    on_activate=lambda x: GLib.idle_add(on_close_callback)
                )
            )
        
        menu_items.append(IgnisMenuSeparator())
        menu_items.append(
            IgnisMenuItem(
                label="Pin" if not app.is_pinned else "Unpin",
                on_activate=lambda x: GLib.idle_add(
                    app.unpin if app.is_pinned else app.pin
                ),
            )
        )
        
        # Add app actions if available
        if app.actions:
            menu_items.append(IgnisMenuSeparator())
            for action in app.actions[:3]:
                menu_items.append(
                    IgnisMenuItem(
                        label=action.name,
                        on_activate=lambda x, action=action: GLib.idle_add(cls.launch_app_action, action),
                    )
                )
        
        return IgnisMenuModel(*menu_items)