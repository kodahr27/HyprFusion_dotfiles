import os
import socket
import threading
from typing import Callable, Set, Dict, List, Any
from gi.repository import GLib
from ignis.services.hyprland import HyprlandService
from ignis.services.applications import ApplicationsService

from .window_matcher import WindowMatcher


class WindowState:
    """Represents current window state data"""
    def __init__(self):
        self.windows: List[Any] = []
        self.app_groups: Dict[str, Dict] = {}
        self.last_update_time: float = 0


class HyprlandIPCListener:
    """Hyprland IPC socket listener for window events"""
    
    def __init__(self, on_event_callback: Callable[[str, str], None]):
        self._stop_event = threading.Event()
        self._callback = on_event_callback
        self._socket_path = self._get_socket_path()
        self._thread = None

    def _get_socket_path(self) -> str:
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        instance_sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        if not runtime_dir or not instance_sig:
            raise RuntimeError("Missing required environment variables for Hyprland socket")
        socket_path = os.path.join(runtime_dir, "hypr", instance_sig, ".socket2.sock")
        return socket_path

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._listener_thread, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join()

    def _listener_thread(self):
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self._socket_path)
        except Exception:
            return

        with sock:
            file = sock.makefile("r")
            while not self._stop_event.is_set():
                line = file.readline()
                if not line:
                    break
                line = line.strip()
                if ">>" in line:
                    event_type, event_data = line.split(">>", 1)
                    self._callback(event_type, event_data)


class WindowDetector:
    """
    Central window state detection and distribution system.
    Detects window changes and provides data to other modules.
    """
    
    def __init__(self):
        self.hyprland = HyprlandService.get_default()
        self.applications = ApplicationsService.get_default()
        self._subscribers: Set[Callable[[WindowState], None]] = set()
        self._ipc_listener = None
        self._connected_windows: Set = set()
        self._update_timeout_id = None
        self._current_state = WindowState()
        
        # Connect to hyprland events
        self.hyprland.connect("window_added", self._on_window_added)
        
        # Connect existing windows
        for win in self.hyprland.windows:
            self._connect_window_closed(win)
        
        # Initial state detection
        self._detect_window_state()
    
    def subscribe(self, callback: Callable[[WindowState], None]):
        """Subscribe to window state changes"""
        self._subscribers.add(callback)
        
        # Send current state to new subscriber
        callback(self._current_state)
        
        # Start IPC listener when first subscriber joins
        if len(self._subscribers) == 1 and not self._ipc_listener:
            self._ipc_listener = HyprlandIPCListener(self._on_ipc_event)
            self._ipc_listener.start()
    
    def unsubscribe(self, callback: Callable[[WindowState], None]):
        """Unsubscribe from window state changes"""
        self._subscribers.discard(callback)
        
        # Stop IPC listener when no subscribers left
        if len(self._subscribers) == 0 and self._ipc_listener:
            self._ipc_listener.stop()
            self._ipc_listener = None
    
    def get_current_state(self) -> WindowState:
        """Get current window state (read-only)"""
        return self._current_state
    
    def _connect_window_closed(self, win):
        """Connect to window closed event"""
        if win not in self._connected_windows:
            win.connect("closed", self._on_window_changed)
            self._connected_windows.add(win)
    
    def _on_window_added(self, hyprland_service, window):
        """Handle window added event"""
        self._connect_window_closed(window)
        self._schedule_state_update("window_added")
    
    def _on_ipc_event(self, event_type: str, event_data: str):
        """Handle IPC events from Hyprland"""
        self._schedule_state_update(f"ipc_{event_type}")
    
    def _on_window_changed(self, *args):
        """Handle generic window change event"""
        self._schedule_state_update("window_changed")
    
    def _schedule_state_update(self, trigger: str):
        """Schedule state detection with debouncing"""
        # Cancel any pending update
        if self._update_timeout_id:
            GLib.source_remove(self._update_timeout_id)
        
        # Schedule update with minimal delay for debouncing
        self._update_timeout_id = GLib.timeout_add(30, self._detect_window_state_and_notify, trigger)
    
    def _detect_window_state_and_notify(self, trigger: str):
        """Detect window state and notify subscribers"""
        self._detect_window_state()
        self._notify_subscribers()
        self._update_timeout_id = None
        return False
    
    def _detect_window_state(self):
        """Detect and update current window state"""
        import time
        
        # Update window list
        self._current_state.windows = list(self.hyprland.windows)
        self._current_state.last_update_time = time.time()
        
        # Group windows by application using the shared matcher
        self._current_state.app_groups = WindowMatcher.group_windows_by_app(
            self._current_state.windows, 
            self.applications
        )
    
    def _notify_subscribers(self):
        """Notify all subscribers of state change"""
        for callback in self._subscribers.copy():
            try:
                callback(self._current_state)
            except Exception:
                pass
    
    def cleanup(self):
        """Cleanup resources"""
        if self._ipc_listener:
            self._ipc_listener.stop()
        self._subscribers.clear()
        self._connected_windows.clear()


# Global instance
_window_detector = None


def get_window_detector() -> WindowDetector:
    """Get the global window detector instance"""
    global _window_detector
    if _window_detector is None:
        _window_detector = WindowDetector()
    return _window_detector
