import os
import socket
import threading
import logging
from typing import Callable, Set
from gi.repository import GLib
from ignis.services.hyprland import HyprlandService

logger = logging.getLogger("WindowEventManager")

class HyprlandIPCListener:
    """Hyprland IPC socket listener for window events"""
    
    def __init__(self, on_closewindow_callback: Callable[[str], None]):
        self._stop_event = threading.Event()
        self._callback = on_closewindow_callback
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
        logger.info("Hyprland IPC listener started")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join()
        logger.info("Hyprland IPC listener stopped")

    def _listener_thread(self):
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self._socket_path)
            logger.info(f"Connected to Hyprland IPC socket at {self._socket_path}")
        except Exception as e:
            logger.error(f"Failed to connect to Hyprland IPC socket: {e}")
            return

        with sock:
            file = sock.makefile("r")
            while not self._stop_event.is_set():
                line = file.readline()
                if not line:
                    break
                line = line.strip()
                if line.startswith("closewindow>>"):
                    window_address = line.split(">>", 1)[-1]
                    logger.debug(f"Received closewindow event for {window_address}")
                    self._callback(window_address)
        logger.info("Exiting Hyprland IPC listener thread")


class WindowEventManager:
    """Manages window events and provides fine-grained event handling for taskbar modules"""
    
    def __init__(self):
        self.hyprland = HyprlandService.get_default()
        self._subscribers: Set[Callable] = set()
        self._ipc_listener = None
        self._connected_windows: Set = set()

        self.hyprland.connect("window_added", self._on_window_added)
        
        # Connect 'closed' to existing windows only (no 'changed' signal)
        for win in self.hyprland.windows:
            self._connect_window_closed(win)

    def subscribe(self, callback: Callable):
        self._subscribers.add(callback)
        
        if len(self._subscribers) == 1 and not self._ipc_listener:
            self._ipc_listener = HyprlandIPCListener(self._on_window_closed_event)
            self._ipc_listener.start()
    
    def unsubscribe(self, callback: Callable):
        self._subscribers.discard(callback)
        
        if len(self._subscribers) == 0 and self._ipc_listener:
            self._ipc_listener.stop()
            self._ipc_listener = None
    
    def _connect_window_closed(self, win):
        if win not in self._connected_windows:
            win.connect("closed", lambda *args, w=win: self._on_window_closed(w))
            self._connected_windows.add(win)

    def _on_window_added(self, hyprland_service, window):
        self._connect_window_closed(window)
        self._notify_subscribers("window_added", window)

    def _on_window_closed_event(self, window_address: str):
        logger.debug(f"Window closed event from IPC for {window_address}")
        self._notify_subscribers("window_closed", window_address)
    
    def _on_window_closed(self, window):
        self._notify_subscribers("window_closed", window)

    def _notify_subscribers(self, event_type: str, window):
        for callback in self._subscribers.copy():
            try:
                callback(event_type, window)
            except Exception as e:
                logger.error(f"Error in window event callback: {e}")

    def cleanup(self):
        if self._ipc_listener:
            self._ipc_listener.stop()
        self._subscribers.clear()
        self._connected_windows.clear()


# Global instance
_window_event_manager = None

def get_window_event_manager() -> WindowEventManager:
    global _window_event_manager
    if _window_event_manager is None:
        _window_event_manager = WindowEventManager()
    return _window_event_manager
