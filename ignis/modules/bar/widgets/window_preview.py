import os
import logging
import threading
import time
import subprocess
import tempfile
from typing import Any, Callable, Dict, List, Optional

from gi.repository import Gtk, GdkPixbuf, GLib, Gdk
from ignis import widgets
from ignis.services.hyprland import HyprlandService

logger = logging.getLogger(__name__)


class WindowPreviewWidget(widgets.Box):
    PREVIEW_WIDTH = 250
    PREVIEW_HEIGHT = 170
    REFRESH_INTERVAL_MS = 100  # throttle capture interval (ms)

    def __init__(self, window: Any, on_click: Optional[Callable] = None):
        super().__init__(orientation="vertical", spacing=4, css_classes=["window-preview"])
        self._window = window
        self._on_click = on_click
        self._preview_image = widgets.Picture()
        self._preview_image.set_size_request(self.PREVIEW_WIDTH, self.PREVIEW_HEIGHT)
        self._preview_image.css_classes = ["window-preview-image"]

        window_title = getattr(window, "title", "") or "Untitled"
        self._title_label = widgets.Label(
            label=window_title, css_classes=["window-preview-title"], ellipsize="end"
        )

        self.append(self._preview_image)
        self.append(self._title_label)

        if on_click:
            self.on_click = lambda x: on_click(window)

        self._last_pixbuf: Optional[GdkPixbuf.Pixbuf] = None
        self._running = True

        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()

    def _update_loop(self):
        while self._running:
            try:
                pixbuf = self._capture_window_thumbnail()
                if pixbuf:
                    self._last_pixbuf = pixbuf
                    GLib.idle_add(self._update_texture, pixbuf)
                elif self._last_pixbuf:
                    # Reuse last successful capture
                    GLib.idle_add(self._update_texture, self._last_pixbuf)
                else:
                    # Show fallback only once
                    if not hasattr(self, '_fallback_shown'):
                        GLib.idle_add(self._set_fallback_preview)
                        self._fallback_shown = True
            except Exception as e:
                logger.debug(f"Preview update failed: {e}")
            time.sleep(self.REFRESH_INTERVAL_MS / 1000.0)

    def _update_texture(self, pixbuf):
        try:
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            self._preview_image.paintable = texture
        except Exception as e:
            logger.debug(f"Failed to update texture: {e}")

    def _capture_window_thumbnail(self) -> Optional[GdkPixbuf.Pixbuf]:
        window_address = getattr(self._window, "address", None)
        if not window_address:
            return None

        clean_address = window_address if str(window_address).startswith("0x") else f"0x{window_address}"

        try:
            # Output to stdout using '-'
            result = subprocess.run(
                ["grim", "-w", clean_address, "-"],
                capture_output=True,
                timeout=2
            )
            if result.returncode == 0 and result.stdout:
                loader = GdkPixbuf.PixbufLoader()
                loader.write(result.stdout)
                loader.close()
                pixbuf = loader.get_pixbuf()
                if pixbuf:
                    # Optionally scale the pixbuf for preview
                    return pixbuf.scale_simple(
                        self.PREVIEW_WIDTH, self.PREVIEW_HEIGHT, GdkPixbuf.InterpType.BILINEAR
                    )
        except subprocess.TimeoutExpired:
            logger.debug(f"Screenshot capture timed out for {clean_address}")
        except Exception as e:
            logger.debug(f"Screenshot capture failed: {e}")
        return None

    def _set_fallback_preview(self):
        try:
            surface = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8,
                                           self.PREVIEW_WIDTH, self.PREVIEW_HEIGHT)
            surface.fill(0x404040ff)
            texture = Gdk.Texture.new_for_pixbuf(surface)
            self._preview_image.paintable = texture
        except Exception as e:
            logger.debug(f"Failed to set fallback preview: {e}")

    def stop(self):
        self._running = False

    def __del__(self):
        self.stop()


class WindowPreviewPopover(widgets.Window):
    MAX_COLUMNS = 3
    SPACING = 8
    PADDING = 12

    def __init__(self, windows: List[Any], app_name: str, app_id: str):
        super().__init__(
            namespace=f"window-preview-{app_id}",
            name=f"window-preview-popup-{app_id}",
            layer="overlay",
            anchor=["top", "left"],
            css_classes=["window-preview-popover"]
        )
        self._windows = windows
        self._app_name = app_name
        self._app_id = app_id
        self._preview_widgets: List[WindowPreviewWidget] = []
        
        self._setup_content()
        self.set_size_request(250, 180)
        self.visible = False

    def _setup_content(self):
        try:
            main_box = widgets.Box(orientation="vertical", spacing=self.SPACING, css_classes=["preview-container"])
            main_box.set_margin_top(self.PADDING)
            main_box.set_margin_bottom(self.PADDING)
            main_box.set_margin_start(self.PADDING)
            main_box.set_margin_end(self.PADDING)

            if len(self._windows) > 1:
                header = widgets.Label(
                    label=f"{self._app_name} ({len(self._windows)} windows)",
                    css_classes=["window-preview-header"]
                )
                main_box.append(header)

            preview_container = self._create_preview_grid()
            if preview_container:
                main_box.append(preview_container)
            self.child = main_box
        except Exception as e:
            logger.error(f"Failed to setup popover content: {e}")
            self.child = widgets.Label(label=f"{self._app_name}\nPreview unavailable")

    def _create_preview_grid(self) -> Optional[widgets.Widget]:
        try:
            if len(self._windows) == 1:
                preview = WindowPreviewWidget(self._windows[0], self._on_window_clicked)
                self._preview_widgets.append(preview)
                return preview

            container = widgets.Box(orientation="vertical", spacing=self.SPACING)
            current_row = None
            for i, window in enumerate(self._windows):
                if i % self.MAX_COLUMNS == 0:
                    current_row = widgets.Box(orientation="horizontal", spacing=self.SPACING)
                    container.append(current_row)
                preview = WindowPreviewWidget(window, self._on_window_clicked)
                self._preview_widgets.append(preview)
                current_row.append(preview)
            return container
        except Exception as e:
            logger.error(f"Failed to create preview grid: {e}")
            return None

    def _on_window_clicked(self, window: Any):
        try:
            hyprland = HyprlandService.get_default()
            window_address = getattr(window, "address", None)
            if window_address:
                hyprland.dispatch("focuswindow", f"address:{window_address}")
            else:
                title = getattr(window, "title", "")
                if title:
                    hyprland.dispatch("focuswindow", f"title:{title}")
            self.close()
        except Exception as e:
            logger.error(f"Failed to focus window: {e}")
            self.close()

    def show_at_position(self, x: int, y: int):
        self.set_margin_left(x)
        self.set_margin_top(y)
        self.visible = True

    def hide_preview(self):
        self.close()

    def close(self):
        try:
            for widget in self._preview_widgets:
                widget.stop()
            
            self.visible = False
            
            if hasattr(self, "destroy"):
                self.destroy()
        except Exception as e:
            logger.debug(f"Error fully destroying popover: {e}")


class WindowPreviewManager:
    HOVER_DELAY_MS = 800
    HIDE_DELAY_MS = 100

    def __init__(self):
        self._active_popovers: Dict[str, WindowPreviewPopover] = {}
        self._hover_timeouts: Dict[str, int] = {}
        self._hide_timeouts: Dict[str, int] = {}
        self._hyprland = HyprlandService.get_default()

    def show_preview_for_app(self, widget, app_id, windows, app_name, position=None):
        if not windows:
            return

        self._cancel_hide_timeout(app_id)

        if app_id in self._active_popovers:
            prev = self._active_popovers[app_id]
            try:
                prev.close()
            except Exception as e:
                logger.debug(f"Error cleaning up previous popover: {e}")
            del self._active_popovers[app_id]

        try:
            preview_window = WindowPreviewPopover(windows, app_name, app_id)
            self._active_popovers[app_id] = preview_window
            if position and isinstance(position, tuple) and len(position) == 2:
                preview_window.show_at_position(position[0], position[1])
            else:
                preview_window.show_at_position(100, 50)
        except Exception as e:
            logger.error(f"Failed to show preview for {app_name}: {e}")
            if app_id in self._active_popovers:
                del self._active_popovers[app_id]

    def schedule_show_preview(self, widget, app_id, windows, app_name, position=None):
        self._cancel_hover_timeout(app_id)
        timeout_id = GLib.timeout_add(
            self.HOVER_DELAY_MS,
            lambda: self._show_preview_timeout(widget, app_id, windows, app_name, position)
        )
        self._hover_timeouts[app_id] = timeout_id

    def schedule_hide_preview(self, app_id):
        if app_id in self._hover_timeouts:
            return
        self._cancel_hide_timeout(app_id)
        timeout_id = GLib.timeout_add(
            self.HIDE_DELAY_MS,
            lambda: self._hide_preview_timeout(app_id)
        )
        self._hide_timeouts[app_id] = timeout_id

    def cancel_scheduled_show(self, app_id):
        self._cancel_hover_timeout(app_id)

    def cancel_scheduled_hide(self, app_id):
        self._cancel_hide_timeout(app_id)

    def is_preview_visible(self, app_id: str) -> bool:
        preview_window = self._active_popovers.get(app_id)
        return preview_window is not None and preview_window.visible

    def _show_preview_timeout(self, widget, app_id, windows, app_name, position=None) -> bool:
        if app_id in self._hover_timeouts:
            del self._hover_timeouts[app_id]
        self.show_preview_for_app(widget, app_id, windows, app_name, position)
        return False

    def hide_preview_for_app(self, app_id):
        preview_window = self._active_popovers.get(app_id)
        if preview_window:
            try:
                preview_window.close()
            except Exception as e:
                logger.debug(f"Error hiding preview: {e}")
            del self._active_popovers[app_id]

    def _hide_preview_timeout(self, app_id) -> bool:
        if app_id in self._hide_timeouts:
            del self._hide_timeouts[app_id]
        self.hide_preview_for_app(app_id)
        return False

    def _cancel_hover_timeout(self, app_id):
        if app_id in self._hover_timeouts:
            GLib.source_remove(self._hover_timeouts[app_id])
            del self._hover_timeouts[app_id]

    def _cancel_hide_timeout(self, app_id):
        if app_id in self._hide_timeouts:
            GLib.source_remove(self._hide_timeouts[app_id])
            del self._hide_timeouts[app_id]

    def cleanup(self):
        for timeout_id in self._hover_timeouts.values():
            GLib.source_remove(timeout_id)
        for timeout_id in self._hide_timeouts.values():
            GLib.source_remove(timeout_id)
        self._hover_timeouts.clear()
        self._hide_timeouts.clear()
        
        for preview_window in list(self._active_popovers.values()):
            try:
                preview_window.close()
            except Exception as e:
                logger.debug(f"Error closing preview window during cleanup: {e}")
        self._active_popovers.clear()


_preview_manager: Optional[WindowPreviewManager] = None


def get_preview_manager() -> WindowPreviewManager:
    global _preview_manager
    if _preview_manager is None:
        _preview_manager = WindowPreviewManager()
    return _preview_manager