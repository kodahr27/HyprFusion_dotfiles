import os
import json
import logging
from typing import List, Dict, Optional
from gi.repository import GLib, Gtk, Gdk, Gio
from ignis import widgets
from ignis.window_manager import WindowManager
from ignis.services.applications import ApplicationsService, Application
from ignis.menu_model import IgnisMenuModel, IgnisMenuItem, IgnisMenuSeparator

from .window_detector import get_window_detector, WindowState
from .badge_counter import get_badge_counter, BadgeInfo
from .app_launcher import AppLauncher
from .window_preview import get_preview_manager

logger = logging.getLogger(__name__)

applications = ApplicationsService.get_default()
window_manager = WindowManager.get_default()
_preview_manager = get_preview_manager()

CONFIG_PATH = os.path.expanduser("~/.config/ignis/app_order.json")


class DragDropMixin:
    """Mixin class providing common drag and drop functionality."""

    def create_drag_icon(self, app: Application, drag_source) -> None:
        paintable = getattr(app, "_preloaded_icon", None)
        if not paintable:
            icon_path = getattr(app, "icon_path", None)
            if icon_path and os.path.isfile(icon_path):
                try:
                    file = Gio.File.new_for_path(icon_path)
                    paintable = Gdk.Texture.new_from_file(file)
                except Exception as e:
                    logger.debug(f"Failed to load icon from path {icon_path}: {e}")

            if paintable is None:
                display = Gdk.Display.get_default()
                icon_theme = Gtk.IconTheme.get_for_display(display)
                icon_names = [app.icon, "application-x-executable"]
                for icon_name in icon_names:
                    try:
                        paintable = icon_theme.lookup_icon(
                            icon_name, None, 24, 1, Gtk.TextDirection.LTR, 0
                        )
                        if paintable:
                            break
                    except Exception as e:
                        logger.debug(f"Failed to load icon {icon_name}: {e}")

            app._preloaded_icon = paintable

        if paintable:
            drag_source.set_icon(paintable, 12, 12)

    def setup_drop_target(self, widget, on_drop_callback) -> Gtk.DropTarget:
        drop_target = Gtk.DropTarget()
        drop_target.set_gtypes([str])
        drop_target.set_actions(Gdk.DragAction.MOVE)
        drop_target.connect("drop", on_drop_callback)
        drop_target.connect("enter", self._on_drop_enter)
        drop_target.connect("leave", self._on_drop_leave)
        drop_target.connect("motion", self._on_drop_motion)
        widget.add_controller(drop_target)
        return drop_target

    def _on_drop_enter(self, drop_target, x, y):
        if hasattr(self, 'add_css_class'):
            self.add_css_class("drag-hover")
        return Gdk.DragAction.MOVE

    def _on_drop_leave(self, drop_target):
        if hasattr(self, 'remove_css_class'):
            self.remove_css_class("drag-hover")

    def _on_drop_motion(self, drop_target, x, y):
        return Gdk.DragAction.MOVE


class PinnedAppGroup(widgets.Button, DragDropMixin):
    CLICK_DELAY_MS = 150

    def __init__(self, app: Application, app_container: 'Apps'):
        super().__init__()
        self._app = app
        self._app_container = app_container
        self._is_dragging = False
        self._is_hovering = False
        self._current_badge_info: Optional[BadgeInfo] = None
        self._click_timeout: Optional[int] = None

        self._setup_ui()
        self._setup_drag_and_drop()
        self._setup_event_handlers()
        self._setup_hover_events()

    def _setup_ui(self) -> None:
        self._icon_box = widgets.Box(spacing=0)
        self._icon_widget = widgets.Icon(image=self._app.icon, pixel_size=32)
        self._icon_box.append(self._icon_widget)

        self._count_label = widgets.Label(css_classes=["taskbar-count-badge"], visible=False)
        self._icon_box.append(self._count_label)

        self._menu = self._create_menu()
        main_box = widgets.Box()
        main_box.append(self._icon_box)
        main_box.append(self._menu)

        self.child = main_box
        self.css_classes = ["taskbar-pinned-apps", "unset"]

    def _create_menu(self) -> widgets.PopoverMenu:
        menu_items = [
            IgnisMenuItem(label="Launch", on_activate=lambda x: AppLauncher.launch_app_delayed(self._app)),
            IgnisMenuSeparator(),
            IgnisMenuItem(label="Unpin", on_activate=lambda x: self._unpin_app()),
        ]
        for action in self._app.actions:
            menu_items.append(
                IgnisMenuItem(label=action.name, on_activate=lambda x, action=action: AppLauncher.launch_app_action(action))
            )
        return widgets.PopoverMenu(model=IgnisMenuModel(*menu_items))

    def _setup_event_handlers(self) -> None:
        self.on_click = self._handle_click
        self.on_right_click = lambda x: self._menu.popup()

    def _setup_hover_events(self) -> None:
        main_box = self.child
        self._hover_controller = Gtk.EventControllerMotion()
        self._hover_controller.connect("enter", self._on_hover_enter)
        self._hover_controller.connect("leave", self._on_hover_leave)
        main_box.add_controller(self._hover_controller)

    def _setup_drag_and_drop(self) -> None:
        self._drag_source = Gtk.DragSource()
        self._drag_source.set_actions(Gdk.DragAction.MOVE)
        self._content_provider = Gdk.ContentProvider.new_for_value(self._app.id)
        self._drag_source.set_content(self._content_provider)
        self._drag_source.connect("prepare", self._on_drag_prepare)
        self._drag_source.connect("drag-begin", self._on_drag_begin)
        self._drag_source.connect("drag-end", self._on_drag_end)
        self._drag_source.connect("drag-cancel", self._on_drag_cancel)
        self.add_controller(self._drag_source)
        self.setup_drop_target(self, self._on_drop)

    def update_badge(self, badge_info: BadgeInfo) -> None:
        self._current_badge_info = badge_info
        def _update():
            if badge_info.visible and badge_info.count > 0:
                self._count_label.set_label(str(badge_info.count))
                self._count_label.set_visible(True)
            else:
                self._count_label.set_label("")
                self._count_label.set_visible(False)
        GLib.idle_add(_update)

    def _unpin_app(self) -> None:
        try:
            self._app.unpin()
        except Exception as e:
            logger.error(f"Failed to unpin app {self._app.name}: {e}")

    # Drag & Drop handlers
    def _on_drag_prepare(self, drag_source, x, y):
        self._cancel_click_timeout()
        self._is_dragging = True
        self.add_css_class("dragging")
        return self._content_provider

    def _on_drag_begin(self, drag_source, drag):
        self._is_dragging = True
        self.add_css_class("dragging")
        self.create_drag_icon(self._app, drag_source)

    def _on_drag_end(self, drag_source, drag, delete_data):
        self._is_dragging = False
        self.remove_css_class("dragging")
        self.remove_css_class("drag-hover")
        return False

    def _on_drag_cancel(self, drag_source, drag, reason):
        self._is_dragging = False
        self.remove_css_class("dragging")
        self.remove_css_class("drag-hover")
        return False

    def _on_drop(self, drop_target, value, x, y):
        self.remove_css_class("drag-hover")
        return False

    # Hover preview
    def _on_hover_enter(self, controller=None, x=None, y=None):
        self._is_hovering = True
        if self._current_badge_info and self._current_badge_info.windows and not self._is_dragging:
            _preview_manager.cancel_scheduled_hide(self._app.id)
            GLib.idle_add(self._schedule_preview_show)

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
        num_windows = len(self._current_badge_info.windows)
        num_columns = min(num_windows, MAX_COLUMNS)
        num_rows = (num_windows + MAX_COLUMNS - 1) // MAX_COLUMNS
        total_width = num_columns * PREVIEW_WIDTH + (num_columns - 1) * SPACING
        total_height = num_rows * PREVIEW_HEIGHT + (num_rows - 1) * SPACING
        preview_x = alloc.x + x - ((total_width - ICON_WIDTH) // 2)
        preview_y = alloc.y + y + VERTICAL_MARGIN
        return preview_x, preview_y

    def _schedule_preview_show(self) -> bool:
        if self._is_hovering and self._current_badge_info and self._current_badge_info.windows and not self._is_dragging:
            root_widget = self.get_root()
            if root_widget:
                x, y = self._calculate_preview_position()
                _preview_manager.schedule_show_preview(
                    self,
                    self._app.id,
                    self._current_badge_info.windows,
                    self._app.name,
                    position=(x, y)
                )
        return False

    def _on_hover_leave(self, controller=None, x=None, y=None):
        self._is_hovering = False
        _preview_manager.cancel_scheduled_show(self._app.id)
        _preview_manager.schedule_hide_preview(self._app.id)

    # Click handling
    def _handle_click(self, widget) -> None:
        if not self._is_dragging:
            if _preview_manager.is_preview_visible(self._app.id):
                _preview_manager.hide_preview_for_app(self._app.id)
            self._cancel_click_timeout()
            self._click_timeout = GLib.timeout_add(self.CLICK_DELAY_MS, self._execute_click)

    def _execute_click(self) -> bool:
        self._click_timeout = None
        if not self._is_dragging:
            if self._current_badge_info and self._current_badge_info.windows:
                GLib.idle_add(AppLauncher.focus_or_launch, self._app, self._current_badge_info.windows)
            else:
                GLib.idle_add(AppLauncher.launch_app, self._app)
        return False

    def _cancel_click_timeout(self) -> None:
        if self._click_timeout is not None:
            GLib.source_remove(self._click_timeout)
            self._click_timeout = None

    def cleanup(self) -> None:
        self._cancel_click_timeout()
        _preview_manager.cancel_scheduled_show(self._app.id)
        _preview_manager.cancel_scheduled_hide(self._app.id)


class AnchorDropTarget(widgets.Box, DragDropMixin):
    def __init__(self, app_container: 'Apps', target_app_id: str):
        super().__init__(css_classes=["drop-anchor"])
        self._app_container = app_container
        self._target_app_id = target_app_id
        self.setup_drop_target(self, self._on_drop)

    def _on_drop(self, drop_target, value, x, y) -> bool:
        if value and isinstance(value, str):
            dragged_app_id = value
            if dragged_app_id != self._target_app_id:
                self._app_container.reorder_pinned_apps(dragged_app_id, self._target_app_id)
                return True
        return False


class AppOrderManager:
    def __init__(self, config_path: str):
        self._config_path = config_path
        self._order: List[str] = []
        self._save_scheduled = False
        self._load_order()

    def _load_order(self) -> None:
        try:
            if os.path.exists(self._config_path):
                with open(self._config_path, "r") as f:
                    data = json.load(f)
                if isinstance(data, list) and all(isinstance(item, str) for item in data):
                    self._order = data
                else:
                    logger.warning("Invalid app order format, resetting to empty")
                    self._order = []
            else:
                self._order = []
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load app order: {e}")
            self._order = []

    def save_order(self) -> None:
        if not self._save_scheduled:
            self._save_scheduled = True
            GLib.idle_add(self._perform_save)

    def _perform_save(self) -> bool:
        self._save_scheduled = False
        try:
            os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
            with open(self._config_path, "w") as f:
                json.dump(self._order, f, indent=2)
        except (IOError, OSError) as e:
            logger.error(f"Failed to save app order: {e}")
        return False

    def sync_with_pinned_apps(self, pinned_apps: List[Application]) -> None:
        current_pinned_ids = {app.id for app in pinned_apps}
        self._order = [app_id for app_id in self._order if app_id in current_pinned_ids]
        for app in pinned_apps:
            if app.id not in self._order:
                self._order.append(app.id)
        self.save_order()

    def get_ordered_apps(self, pinned_apps: List[Application]) -> List[Application]:
        apps_dict = {app.id: app for app in pinned_apps}
        ordered_apps = []
        for app_id in self._order:
            if app_id in apps_dict:
                ordered_apps.append(apps_dict[app_id])
        for app in pinned_apps:
            if app not in ordered_apps:
                ordered_apps.append(app)
        return ordered_apps

    def reorder(self, dragged_app_id: str, target_app_id: str) -> None:
        if dragged_app_id == target_app_id:
            return
        try:
            self._order.remove(dragged_app_id)
        except ValueError:
            pass
        try:
            target_index = self._order.index(target_app_id)
            self._order.insert(target_index, dragged_app_id)
        except ValueError:
            self._order.append(dragged_app_id)
        self.save_order()


class Apps(widgets.Box):
    def __init__(self):
        super().__init__(spacing=4)
        self._window_detector = get_window_detector()
        self._badge_counter = get_badge_counter()
        self._order_manager = AppOrderManager(CONFIG_PATH)
        self._pinned_app_widgets: Dict[str, PinnedAppGroup] = {}
        self._update_scheduled = False

        self._setup_event_handlers()
        self._initial_setup()

    def _setup_event_handlers(self) -> None:
        applications.connect("notify::pinned", self._on_pinned_changed)
        self._window_detector.subscribe(self._on_window_state_changed)

    def _initial_setup(self) -> None:
        self._order_manager.sync_with_pinned_apps(list(applications.pinned))
        self._schedule_update()

    def _on_pinned_changed(self, *args) -> None:
        self._order_manager.sync_with_pinned_apps(list(applications.pinned))
        self._schedule_update()

    def _on_window_state_changed(self, window_state: WindowState) -> None:
        GLib.idle_add(self._update_badges, window_state)

    def _schedule_update(self) -> None:
        if not self._update_scheduled:
            self._update_scheduled = True
            GLib.idle_add(self._perform_update)

    def _perform_update(self) -> bool:
        self._update_scheduled = False
        self._refresh_pinned_apps()
        return False

    def reorder_pinned_apps(self, dragged_app_id: str, target_app_id: str) -> None:
        self._order_manager.reorder(dragged_app_id, target_app_id)
        self._schedule_update()

    def _update_badges(self, window_state: WindowState) -> None:
        pinned_apps = list(applications.pinned)
        badges = self._badge_counter.compute_badges_for_apps(window_state, pinned_apps)
        for app in pinned_apps:
            widget = self._pinned_app_widgets.get(app.id)
            badge_info = badges.get(app.id)
            if widget and badge_info:
                widget.update_badge(badge_info)

    def _refresh_pinned_apps(self) -> None:
        old_widgets = list(self._pinned_app_widgets.values())
        self._pinned_app_widgets.clear()
        pinned_apps = self._order_manager.get_ordered_apps(list(applications.pinned))
        widgets_list = []

        if pinned_apps:
            widgets_list.append(AnchorDropTarget(self, pinned_apps[0].id))

        for i, app in enumerate(pinned_apps):
            app_widget = PinnedAppGroup(app, self)
            self._pinned_app_widgets[app.id] = app_widget
            widgets_list.append(app_widget)
            if i + 1 < len(pinned_apps):
                widgets_list.append(AnchorDropTarget(self, pinned_apps[i + 1].id))

        start_button = self._create_start_button()
        widgets_list.append(start_button)

        self.child = widgets_list

        for widget in old_widgets:
            widget.cleanup()

        current_state = self._window_detector.get_current_state()
        GLib.idle_add(self._update_badges, current_state)

    def _create_start_button(self) -> widgets.Button:
        return widgets.Button(
            child=widgets.Icon(image="start-here-symbolic", pixel_size=32),
            on_click=self._toggle_launcher,
            css_classes=["taskbar-pinned-apps", "unset"]
        )

    def _toggle_launcher(self, widget) -> None:
        GLib.idle_add(window_manager.toggle_window, "ignis_LAUNCHER")

    def cleanup(self) -> None:
        try:
            self._window_detector.unsubscribe(self._on_window_state_changed)
        except Exception as e:
            logger.error(f"Failed to unsubscribe from window detector: {e}")
        for widget in self._pinned_app_widgets.values():
            try:
                widget.cleanup()
            except Exception as e:
                logger.error(f"Failed to cleanup app widget: {e}")
        self._pinned_app_widgets.clear()

    def get_pinned_app_count(self) -> int:
        return len(self._pinned_app_widgets)

    def get_widget_for_app(self, app_id: str) -> Optional[PinnedAppGroup]:
        return self._pinned_app_widgets.get(app_id)
