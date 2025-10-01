from gi.repository import Gtk, GLib
from ignis import widgets
from ignis.services.applications import ApplicationsService, Application
from ignis.menu_model import IgnisMenuModel

from .window_detector import get_window_detector, WindowState
from .badge_counter import get_badge_counter, BadgeInfo
from .taskbar_utils import TaskbarUtils
from .window_preview import get_preview_manager

applications = ApplicationsService.get_default()
_preview_manager = get_preview_manager()


class RunningAppGroup(widgets.Button):
    """Represents a single running app with icon, badge, menu, and hover preview."""

    def __init__(self, app: Application, badge_info: BadgeInfo, icon_override=None):
        self._app = app
        self._badge_info = badge_info
        self._is_hovering = False
        self._badge_widget = None

        icon = icon_override if icon_override else app.icon
        self._icon_box = widgets.Box(spacing=0)
        self._icon_widget = widgets.Icon(image=icon, pixel_size=32)
        self._icon_box.append(self._icon_widget)

        if badge_info.count > 1:
            self._badge_widget = widgets.Label(
                label=str(badge_info.count),
                css_classes=["taskbar-count-badge"],
            )
            self._icon_box.append(self._badge_widget)

        # Menu - will be rebuilt dynamically
        self._menu = widgets.PopoverMenu(model=self._build_menu())

        content_box = widgets.Box()
        content_box.append(self._icon_box)
        content_box.append(self._menu)

        # Hover controller
        self._hover_controller = Gtk.EventControllerMotion()
        self._hover_controller.connect("enter", self._on_hover_enter)
        self._hover_controller.connect("leave", self._on_hover_leave)
        content_box.add_controller(self._hover_controller)

        # Click controller
        self._button_controller = Gtk.GestureClick()
        self._button_controller.set_button(0)
        self._button_controller.connect("pressed", self._on_button_pressed)
        content_box.add_controller(self._button_controller)

        super().__init__(
            child=content_box,
            css_classes=["running-apps-group", "unset"],
        )

        self.set_has_tooltip(False)

    def _build_menu(self) -> IgnisMenuModel:
        """Build the context menu using TaskbarUtils utility"""
        return TaskbarUtils.build_app_context_menu(
            app=self._app,
            window_count=self._badge_info.count,
            windows=self._badge_info.windows,
            on_focus_callback=self._focus_windows,
            on_close_callback=self._close_all_windows
        )

    def update_badge_info(self, new_badge_info: BadgeInfo):
        self._badge_info = new_badge_info

        def update_widget():
            if new_badge_info.count > 1:
                if not self._badge_widget:
                    self._badge_widget = widgets.Label(
                        label=str(new_badge_info.count),
                        css_classes=["taskbar-count-badge"],
                    )
                    self._icon_box.append(self._badge_widget)
                else:
                    self._badge_widget.set_label(str(new_badge_info.count))
                    self._badge_widget.set_visible(True)
            else:
                if self._badge_widget:
                    self._badge_widget.set_visible(False)
            
            # Rebuild menu with updated badge info
            self._menu.set_model(self._build_menu())
        
        GLib.idle_add(update_widget)

    def _toggle_pin(self):
        if self._app.is_pinned:
            self._app.unpin()
        else:
            self._app.pin()

    def _focus_windows(self):
        TaskbarUtils.focus_or_launch(self._app, self._badge_info.windows)

    def _close_all_windows(self):
        """Close all windows associated with this app"""
        TaskbarUtils.close_windows(self._badge_info.windows)

    def _calculate_preview_position(self):
        root = self.get_root()
        if root is None:
            return 0, 0

        x, y = self.translate_coordinates(root, 0, 0)
        alloc = root.get_allocation()

        ICON_WIDTH = 32
        PREVIEW_WIDTH = 250
        PREVIEW_HEIGHT = 170
        MAX_COLUMNS = 3
        SPACING = 8
        VERTICAL_MARGIN = 8

        num_windows = len(self._badge_info.windows)
        num_columns = min(num_windows, MAX_COLUMNS)
        num_rows = (num_windows + MAX_COLUMNS - 1) // MAX_COLUMNS

        total_width = num_columns * PREVIEW_WIDTH + (num_columns - 1) * SPACING
        total_height = num_rows * PREVIEW_HEIGHT + (num_rows - 1) * SPACING

        preview_x = alloc.x + x - ((total_width - ICON_WIDTH) // 2)
        preview_y = alloc.y + y + VERTICAL_MARGIN

        return preview_x, preview_y

    def _on_hover_enter(self, controller=None, x=None, y=None):
        self._is_hovering = True
        if self._badge_info.windows:
            _preview_manager.cancel_scheduled_hide(self._app.id)
            GLib.idle_add(self._schedule_preview_show)

    def _schedule_preview_show(self) -> bool:
        if self._is_hovering and self._badge_info.windows:
            root_widget = self.get_root()
            if root_widget:
                x, y = self._calculate_preview_position()
                _preview_manager.schedule_show_preview(
                    self, 
                    self._app.id, 
                    self._badge_info.windows, 
                    self._app.name,
                    position=(x, y)
                )
        return False

    def _on_hover_leave(self, controller=None, x=None, y=None):
        self._is_hovering = False
        _preview_manager.cancel_scheduled_show(self._app.id)
        _preview_manager.schedule_hide_preview(self._app.id)

    def _on_button_pressed(self, gesture, n_press, x, y):
        button = gesture.get_current_button()
        if button == 1:
            if _preview_manager.is_preview_visible(self._app.id):
                _preview_manager.hide_preview_for_app(self._app.id)
            GLib.idle_add(self._focus_windows)
            return True
        elif button == 3:
            if _preview_manager.is_preview_visible(self._app.id):
                _preview_manager.hide_preview_for_app(self._app.id)
            if self._menu.is_visible():
                GLib.idle_add(self._menu.popdown)
            GLib.idle_add(self._menu.popup)
            return True
        return False

    def cleanup(self):
        _preview_manager.cancel_scheduled_show(self._app.id)
        _preview_manager.cancel_scheduled_hide(self._app.id)
        if _preview_manager.is_preview_visible(self._app.id):
            _preview_manager.hide_preview_for_app(self._app.id)


class RunningApps(widgets.Box):
    """Container for all running apps on the taskbar."""

    def __init__(self):
        super().__init__(spacing=4)
        self._window_detector = get_window_detector()
        self._badge_counter = get_badge_counter()
        self._children = []
        self._app_widgets = {}
        self._window_detector.subscribe(self._on_window_state_changed)
        applications.connect(
            "notify::pinned", lambda *args: GLib.idle_add(self._refresh_from_current_state)
        )
        current_state = self._window_detector.get_current_state()
        self._update_from_window_state(current_state)

    def _on_window_state_changed(self, window_state: WindowState):
        GLib.idle_add(self._update_from_window_state, window_state)

    def _refresh_from_current_state(self):
        current_state = self._window_detector.get_current_state()
        GLib.idle_add(self._update_from_window_state, current_state)

    def _update_from_window_state(self, window_state: WindowState):
        running_badges = self._badge_counter.get_running_apps_badges(
            window_state, exclude_pinned=True
        )
        active_app_ids = set()

        for app_id, badge_info in running_badges.items():
            if badge_info.count <= 0:
                continue
            active_app_ids.add(app_id)
            icon_override = None
            for group_key, group_data in window_state.app_groups.items():
                if group_data["app"].id == app_id:
                    icon_override = group_data["icon"]
                    break
            if app_id in self._app_widgets:
                widget = self._app_widgets[app_id]
                widget.update_badge_info(badge_info)
            else:
                widget = RunningAppGroup(
                    badge_info.app,
                    badge_info,
                    icon_override=icon_override
                )
                self.append(widget)
                self._children.append(widget)
                self._app_widgets[app_id] = widget

        widgets_to_remove = [
            (app_id, widget) for app_id, widget in self._app_widgets.items()
            if app_id not in active_app_ids
        ]

        for app_id, widget in widgets_to_remove:
            try:
                widget.cleanup()
                self.remove(widget)
                self._children.remove(widget)
                del self._app_widgets[app_id]
            except Exception:
                pass

        self.queue_draw()

    def cleanup(self):
        for widget in self._children[:]:
            try:
                widget.cleanup()
            except Exception:
                pass
        self._children.clear()
        self._app_widgets.clear()
        try:
            self._window_detector.unsubscribe(self._on_window_state_changed)
        except Exception:
            pass

    def get_app_count(self):
        return len(self._app_widgets)

    def get_widget_for_app(self, app_id):
        return self._app_widgets.get(app_id)