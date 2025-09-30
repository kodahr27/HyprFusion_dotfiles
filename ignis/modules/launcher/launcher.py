import re
import asyncio
import json
import os
from pathlib import Path
from ignis import widgets
from ignis.window_manager import WindowManager
from ignis.services.applications import (
    ApplicationsService,
    Application,
    ApplicationAction,
)
from ignis import utils
from ignis.menu_model import IgnisMenuModel, IgnisMenuItem, IgnisMenuSeparator
from gi.repository import Gio, Gtk, Pango, GLib, Gdk
from typing import Dict, List, Optional, Set, Tuple
from user_options import user_options

# Constants
SEARCH_DEBOUNCE_MS = 150
MAX_SEARCH_RESULTS = 30

window_manager = WindowManager.get_default()
applications = ApplicationsService.get_default()

def get_apps_per_row():
    try:
        return user_options.launcher.apps_per_row
    except Exception:
        return 6

def get_app_spacing():
    try:
        return user_options.launcher.app_spacing
    except Exception:
        return 8

def get_show_labels():
    try:
        return user_options.launcher.show_labels
    except Exception:
        return True

def get_terminal_format():
    try:
        fmt = user_options.launcher.terminal_format
        if fmt and "%command%" in fmt:
            return fmt
    except Exception:
        pass
    return "kitty %command%"

CATEGORIES = {
    'All': {'icon': 'applications-all-symbolic', 'priority': 0},
    'Internet': {'icon': 'applications-internet-symbolic', 'priority': 1},
    'Office': {'icon': 'applications-office-symbolic', 'priority': 2},
    'Multimedia': {'icon': 'applications-multimedia-symbolic', 'priority': 3},
    'Graphics': {'icon': 'applications-graphics-symbolic', 'priority': 4},
    'Development': {'icon': 'applications-development-symbolic', 'priority': 5},
    'Games': {'icon': 'applications-games-symbolic', 'priority': 6},
    'Education': {'icon': 'applications-science-symbolic', 'priority': 7},
    'Utilities': {'icon': 'applications-accessories-symbolic', 'priority': 8},
    'System': {'icon': 'applications-system-symbolic', 'priority': 9},
    'Preferences': {'icon': 'preferences-system-symbolic', 'priority': 10},
}

RECENT_APPS_FILE = Path.home() / ".config" / "ignis" / "recent_apps.json"

def load_recent_apps() -> List[Dict]:
    try:
        if RECENT_APPS_FILE.exists():
            with open(RECENT_APPS_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, list) and data and isinstance(data[0], str):
                    return [{"id": app_id, "count": 1} for app_id in data]
                return data if isinstance(data, list) else []
    except (FileNotFoundError, PermissionError, json.JSONDecodeError) as e:
        print(f"Failed to load recent apps: {e}")
    return []

def save_recent_apps(app_data: List[Dict]) -> None:
    try:
        RECENT_APPS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(RECENT_APPS_FILE, "w") as f:
            json.dump(app_data, f)
    except (FileNotFoundError, PermissionError, json.JSONDecodeError) as e:
        print(f"Failed to save recent apps: {e}")

RECENT_APPS_DATA: List[Dict] = load_recent_apps()

def get_app_by_id(app_id: str) -> Optional[Application]:
    for app in applications.apps:
        if getattr(app, "id", None) == app_id:
            return app
    return None

def get_recent_apps() -> List[Application]:
    result = []
    sorted_data = sorted(RECENT_APPS_DATA, key=lambda x: (-x.get('count', 1), RECENT_APPS_DATA.index(x)))

    for app_data in sorted_data:
        app = get_app_by_id(app_data['id'])
        if app and AppCategorizer.should_show_app(app):
            result.append(app)
    return result

def add_recent_app(app: Application):
    global RECENT_APPS_DATA
    app_id = getattr(app, "id", None)
    if not app_id:
        return

    for i, app_data in enumerate(RECENT_APPS_DATA):
        if app_data['id'] == app_id:
            app_data['count'] = app_data.get('count', 1) + 1
            RECENT_APPS_DATA.insert(0, RECENT_APPS_DATA.pop(i))
            break
    else:
        RECENT_APPS_DATA.insert(0, {"id": app_id, "count": 1})

    RECENT_APPS_DATA = RECENT_APPS_DATA[:user_options.launcher.show_recent_apps and 10 or 0]
    save_recent_apps(RECENT_APPS_DATA)

def clear_recent_apps():
    global RECENT_APPS_DATA
    RECENT_APPS_DATA = []
    save_recent_apps(RECENT_APPS_DATA)


def is_url(url: str) -> bool:
    regex = re.compile(
        r'^(?:http|ftp)s?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|'
        r'\[?[A-F0-9]*:[A-F0-9:]+\]?)'
        r'(?::\d+)?(?:/?|[/?]\S+)$',
        re.IGNORECASE,
    )
    return re.match(regex, url) is not None


class AppCategorizer:
    _desktop_cache = {}

    SKIP_EXACT_NAMES = {
        'avahi-discover', 'bssh', 'bvnc', 'compton', 'dconf editor',
        'assistant', 'qdbusviewer', 'qt assistant', 'designer',
        'linguist', 'qml viewer', 'gdb', 'valgrind'
    }

    SKIP_PATTERNS = {
        'org.gnome.evolution-data-server',
        'org.gnome.geary.background-service',
        'kde-', 'plasma-', 'klipper', 'org.kde.kate.service',
        'im-config', 'orca'
    }

    CATEGORY_KEYWORDS = {
        'Internet': {
            'names': ['firefox', 'chromium', 'chrome', 'brave', 'opera', 'edge', 'safari', 'vivaldi',
                      'thunderbird', 'evolution', 'geary', 'mutt', 'alpine'],
            'categories': ['webbrowser', 'email', 'instantmessaging', 'irc', 'chat', 'network', 'p2p', 'filetransfer', 'telephony', 'videoconference']
        },
        'Development': {
            'names': ['vscode', 'code', 'atom', 'sublime', 'eclipse', 'intellij', 'pycharm', 'android studio', 'qtcreator'],
            'categories': ['development', 'ide', 'debugging', 'profiling', 'revisioncontrol', 'webdevelopment', 'programming', 'building', 'translation']
        },
        'Graphics': {
            'names': ['gimp', 'inkscape', 'blender', 'krita', 'darktable', 'rawtherapee', 'shotwell', 'digikam'],
            'categories': ['graphics', 'photography', 'rastergraphics', 'vectorgraphics', '2dgraphics', '3dgraphics', 'scanning', 'ocr']
        },
        'Office': {
            'names': ['libreoffice', 'writer', 'calc', 'impress', 'onlyoffice', 'wps'],
            'categories': ['office', 'wordprocessor', 'spreadsheet', 'presentation', 'chart', 'database', 'publishing']
        },
        'Multimedia': {
            'names': ['vlc', 'mpv', 'totem', 'rhythmbox', 'audacity', 'obs', 'kdenlive', 'openshot'],
            'categories': ['audiovideo', 'audio', 'video', 'audiovideoediting', 'player', 'recorder', 'discburning', 'sequencer', 'mixer', 'tuner', 'tv']
        },
        'Games': {
            'names': ['steam', 'lutris', 'minecraft', 'playonlinux', 'gamemode'],
            'categories': ['game', 'arcade', 'board', 'card', 'puzzle', 'roleplaying', 'shooter', 'simulation', 'sports', 'strategy']
        },
        'Education': {
            'names': [],
            'categories': ['education', 'science', 'math', 'medicalapplication', 'teaching', 'literature', 'geography', 'geology', 'history', 'biology', 'chemistry', 'computerscience', 'physics', 'astronomy']
        },
        'System': {
            'names': ['terminal', 'console', 'shell', 'gnome-terminal', 'konsole', 'xterm', 'alacritty', 'kitty', 'terminator'],
            'categories': ['system', 'filesystem', 'monitor', 'security', 'accessibility', 'hardwaresettings', 'packagemanager', 'admin']
        },
        'Preferences': {
            'names': ['settings', 'preferences', 'control', 'config'],
            'categories': ['settings', 'preferences', 'desktopsettings', 'x-preferences']
        },
        'Utilities': {
            'names': ['file', 'files', 'manager', 'text editor', 'editor', 'calculator', 'calendar', 'clock', 'weather',
                      'nautilus', 'dolphin', 'thunar', 'pcmanfm', 'nemo', 'gedit', 'kate', 'mousepad', 'pluma', 'leafpad'],
            'categories': ['utility', 'accessories', 'texttools', 'archiving', 'compression', 'filetools', 'calculator', 'clock', 'texteditor', 'viewer', 'filemanager', 'terminal']
        }
    }

    @classmethod
    def get_desktop_categories(cls, app: Application) -> Tuple[Set[str], Optional[str]]:
        app_id = getattr(app, 'id', '')
        if app_id in cls._desktop_cache:
            return cls._desktop_cache[app_id]

        categories = set()
        executable = None
        try:
            if hasattr(app, 'app_info') and app.app_info:
                try:
                    cats = app.app_info.get_categories()
                    if cats:
                        categories.update(cat.strip() for cat in cats.split(';') if cat.strip())
                    try:
                        executable = app.app_info.get_executable()
                    except:
                        pass
                except:
                    pass
            desktop_paths = cls._get_desktop_paths(app)
            for path in desktop_paths:
                if cls._parse_desktop_file(path, categories, executable):
                    if categories:
                        break
            if not categories and app_id:
                try:
                    desktop_app = Gio.DesktopAppInfo.new(app_id)
                    if desktop_app:
                        cats = desktop_app.get_categories()
                        if cats:
                            categories.update(cat.strip() for cat in cats.split(';') if cat.strip())
                        if not executable:
                            try:
                                executable = desktop_app.get_executable()
                            except:
                                pass
                except:
                    pass
        except Exception as e:
            print(f"Error getting categories for {app.name}: {e}")

        result = (categories, executable)
        cls._desktop_cache[app_id] = result
        return result

    @classmethod
    def _get_desktop_paths(cls, app: Application) -> List[str]:
        desktop_paths = []
        if hasattr(app, 'desktop_path') and app.desktop_path:
            desktop_paths.append(app.desktop_path)
        if hasattr(app, 'id') and app.id:
            desktop_id = app.id if app.id.endswith('.desktop') else f"{app.id}.desktop"
            desktop_paths.extend([
                f"/usr/share/applications/{desktop_id}",
                f"/usr/local/share/applications/{desktop_id}",
                f"~/.local/share/applications/{desktop_id}",
            ])
        return desktop_paths

    @classmethod
    def _parse_desktop_file(cls, path: str, categories: Set[str], executable: Optional[str]) -> bool:
        try:
            expanded_path = os.path.expanduser(path)
            if not os.path.exists(expanded_path):
                return False
            with open(expanded_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('Categories='):
                        cats = line.split('=', 1)[1]
                        categories.update(cat.strip() for cat in cats.split(';') if cat.strip())
                    elif line.startswith('Exec=') and not executable:
                        exec_line = line.split('=', 1)[1]
                        executable = exec_line.split()[0] if exec_line else None
            return True
        except (FileNotFoundError, PermissionError, UnicodeDecodeError):
            return False

    @classmethod
    def should_show_app(cls, app: Application) -> bool:
        try:
            if hasattr(app, 'app_info') and app.app_info:
                try:
                    if app.app_info.get_nodisplay():
                        return False
                    only_show_in = app.app_info.get_string('OnlyShowIn')
                    if only_show_in:
                        if 'kde' in only_show_in.lower() or 'xfce' in only_show_in.lower():
                            current_de = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
                            if current_de and 'gnome' in current_de:
                                return False
                    not_show_in = app.app_info.get_string('NotShowIn')
                    if not_show_in and 'gnome' in not_show_in.lower():
                        current_de = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
                        if current_de and 'gnome' in current_de:
                            return False
                except:
                    pass
            app_name_lower = app.name.lower()
            app_id_lower = getattr(app, 'id', '').lower()
            if app_name_lower in cls.SKIP_EXACT_NAMES:
                return False
            for pattern in cls.SKIP_PATTERNS:
                if pattern in app_name_lower or pattern in app_id_lower:
                    return False
            if 'service' in app_name_lower and any(word in app_name_lower for word in ['background', 'daemon', 'helper']):
                return False
            return True
        except Exception as e:
            print(f"Error checking if app should be shown {app.name}: {e}")
            return True

    @classmethod
    def categorize_app(cls, app: Application, categories: Set[str], executable: Optional[str]) -> Optional[str]:
        if not cls.should_show_app(app):
            return None
        categories_lower = {cat.lower() for cat in categories}
        app_name_lower = app.name.lower()
        app_id_lower = getattr(app, 'id', '').lower()
        executable_lower = (executable or '').lower()
        for category, keywords in cls.CATEGORY_KEYWORDS.items():
            if any(name in app_name_lower or name in executable_lower for name in keywords['names']):
                return category
            if any(cat in categories_lower for cat in keywords['categories']):
                return category
        return 'Utilities'


class LauncherAppItem(widgets.Button):
    def __init__(self, application: Application) -> None:
        self._menu = widgets.PopoverMenu()
        self._application = application

        icon_size = user_options.launcher.icon_size if hasattr(user_options.launcher, 'icon_size') else 48
        icon_name = application.icon or "application-x-executable"

        label_visible = get_show_labels()

        label_widget = widgets.Label(
            label=application.name,
            ellipsize="END",
            max_width_chars=20,
            wrap=True,
            xalign=0.5,
            halign="center",
            css_classes=["launcher-app-label"],
        ) if label_visible else None

        children_widgets = [
            widgets.Icon(image=icon_name, pixel_size=icon_size),
        ]

        if label_widget:
            children_widgets.append(label_widget)

        children_widgets.append(self._menu)

        super().__init__(
            on_click=lambda w: self.launch(),
            on_right_click=lambda w: self._menu.popup(),
            css_classes=["launcher-app"],
            child=widgets.Box(
                vertical=True,
                spacing=get_app_spacing(),
                child=children_widgets,
            ),
            hexpand=True,
            vexpand=False,
        )
        self._sync_menu()
        application.connect("notify::is-pinned", lambda w, p: self._sync_menu())

    def launch(self) -> None:
        terminal_fmt = get_terminal_format()
        cmd = self._application.app_info.get_executable() if hasattr(self._application, 'app_info') and self._application.app_info else None
        if cmd:
            command = terminal_fmt.replace("%command%", cmd)
            asyncio.create_task(utils.exec_sh_async(command))
        else:
            self._application.launch()
        add_recent_app(self._application)
        window_manager.close_window("ignis_LAUNCHER")

    def launch_action(self, action: ApplicationAction) -> None:
        action.launch()
        add_recent_app(self._application)
        window_manager.close_window("ignis_LAUNCHER")

    def _sync_menu(self) -> None:
        menu_items = [
            IgnisMenuItem(label="Launch", on_activate=lambda _: self.launch()),
            IgnisMenuSeparator(),
        ]
        for action in self._application.actions:
            menu_items.append(
                IgnisMenuItem(
                    label=action.name,
                    on_activate=lambda _, action=action: self.launch_action(action),
                )
            )
        if self._application.actions:
            menu_items.append(IgnisMenuSeparator())
        if self._application.is_pinned:
            menu_items.append(
                IgnisMenuItem(label="Unpin", on_activate=lambda _: self._application.unpin())
            )
        else:
            menu_items.append(
                IgnisMenuItem(label="Pin", on_activate=lambda _: self._application.pin())
            )
        self._menu.model = IgnisMenuModel(*menu_items)


class SearchWebButton(widgets.Button):
    def __init__(self, query: str):
        self._url = ""

        try:
            browser_desktop_file = utils.exec_sh("xdg-settings get default-web-browser").stdout.strip()
            app_info = Gio.DesktopAppInfo.new(desktop_id=browser_desktop_file)
            icon_name = "applications-internet-symbolic"

            if app_info:
                icon_string = app_info.get_string("Icon")
                if icon_string:
                    icon_name = icon_string
        except:
            icon_name = "applications-internet-symbolic"

        if not query.startswith(("http://", "https://")) and "." in query:
            query = "https://" + query

        if is_url(query):
            label = f"Visit {query}"
            self._url = query
        else:
            label = "Search in Google"
            self._url = f"https://www.google.com/search?q={query.replace(' ', '+')}"

        super().__init__(
            on_click=lambda w: self.launch(),
            css_classes=["launcher-app", "launcher-web-search"],
            child=widgets.Box(
                vertical=True,
                spacing=get_app_spacing(),
                child=[
                    widgets.Icon(image=icon_name, pixel_size=user_options.launcher.icon_size),
                    widgets.Label(label=label, css_classes=["launcher-app-label"]) if get_show_labels() else None,
                ]
            ),
            hexpand=True,
            vexpand=False,
        )

    def launch(self) -> None:
        asyncio.create_task(utils.exec_sh_async(f"xdg-open {self._url}"))
        window_manager.close_window("ignis_LAUNCHER")


class CategoryButton(widgets.Button):
    def __init__(self, category: str, app_count: int, on_click_callback):
        category_info = CATEGORIES.get(category, {'icon': 'applications-other-symbolic'})
        super().__init__(
            label=f"{category} ({app_count})",
            css_classes=["launcher-category-button"],
            on_click=lambda w: on_click_callback(category),
            child=widgets.Box(
                spacing=8,
                child=[
                    widgets.Icon(icon_name=category_info['icon'], pixel_size=16),
                    widgets.Label(label=f"{category} ({app_count})"),
                ]
            )
        )

    def set_active(self, active: bool) -> None:
        if active:
            if "active" not in self.css_classes:
                self.css_classes = self.css_classes + ["active"]
        else:
            self.css_classes = [cls for cls in self.css_classes if cls != "active"]

class RecentAppsContainer(widgets.Box):
    def __init__(self):
        super().__init__(
            vertical=True,
            spacing=8,
            hexpand=True,
            vexpand=False,
            css_classes=["launcher-recent-container"],
        )

        header_box = widgets.Box(
            spacing=8,
            hexpand=True,
            halign="start",
            child=[
                widgets.Label(
                    label="Recent Applications",
                    css_classes=["launcher-recent-title"],
                    halign="start",
                    xalign=0,
                ),
                widgets.Button(
                    label="Clear Recent",
                    css_classes=["launcher-clear-button"],
                    on_click=lambda _: self.clear_recent(),
                ),
            ],
        )

        self._apps_grid = Gtk.Grid()
        self._apps_grid.set_row_spacing(get_app_spacing())
        self._apps_grid.set_column_spacing(get_app_spacing())
        self._apps_grid.set_hexpand(True)
        self._apps_grid.set_vexpand(False)
        self._apps_grid.set_halign(Gtk.Align.FILL)
        self._apps_grid.set_valign(Gtk.Align.START)
        self._apps_grid.add_css_class("launcher-recent-grid")

        # Make all columns equal width for even spacing
        self._apps_grid.set_column_homogeneous(True)

        self.append(header_box)
        self.append(self._apps_grid)

        self.refresh()

    def clear_recent(self):
        clear_recent_apps()
        self.refresh()

    def refresh(self):
        if not user_options.launcher.show_recent_apps:
            self.visible = False
            return

        # Clear all children safely
        child = self._apps_grid.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self._apps_grid.remove(child)
            child = next_child

        recent_apps = get_recent_apps()

        max_cols = user_options.launcher.recent_apps_per_row
        max_rows = user_options.launcher.recent_apps_rows
        max_items = max_cols * max_rows

        recent_apps = recent_apps[:max_items]

        for index, app in enumerate(recent_apps):
            row = index // max_cols
            col = index % max_cols
            app_item = LauncherAppItem(app)
            # Enable expansion to fill grid cell
            app_item.set_hexpand(True)
            self._apps_grid.attach(app_item, col, row, 1, 1)

        self.visible = bool(recent_apps)

class CategorizedAppsPage(widgets.Box):
    def __init__(self, categorized_apps: Dict[str, List[Application]]):
        super().__init__(
            vertical=True,
            css_classes=["launcher-app-category-page"],
            hexpand=True,
            vexpand=True,
            spacing=12
        )
        self._first_app_item = None
        self._categorized_apps = categorized_apps
        self._current_category = None
        self._category_buttons = {}
        self._app_items = []  # Track for keyboard navigation

        self._create_ui()

        if categorized_apps:
            first_category = list(categorized_apps.keys())[0]
            self._show_category(first_category)

    def _create_ui(self) -> None:
        self._category_flowbox = Gtk.FlowBox()
        self._category_flowbox.set_homogeneous(False)
        self._category_flowbox.set_row_spacing(8)
        self._category_flowbox.set_column_spacing(8)
        self._category_flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._category_flowbox.set_max_children_per_line(10)
        self._category_flowbox.set_min_children_per_line(1)
        self._category_flowbox.add_css_class("launcher-category-tabs")
        self._category_flowbox.set_margin_start(16)
        self._category_flowbox.set_margin_end(16)
        self._category_flowbox.set_margin_top(8)
        self._category_flowbox.set_margin_bottom(16)

        self._apps_display_area = widgets.Box(vertical=True, hexpand=True, vexpand=True)

        self.append(self._category_flowbox)
        self.append(self._apps_display_area)

        self._create_category_buttons()

    def _create_category_buttons(self) -> None:
        sorted_categories = sorted(
            self._categorized_apps.keys(),
            key=lambda cat: CATEGORIES.get(cat, {'priority': 999})['priority']
        )
        for category in sorted_categories:
            app_count = len(self._categorized_apps[category])
            button = CategoryButton(category, app_count, self._show_category)
            self._category_buttons[category] = button
            self._category_flowbox.append(button)

    def _show_category(self, category: str) -> None:
        if category not in self._categorized_apps:
            return
        self._current_category = category
        apps = self._categorized_apps[category]
        for cat, button in self._category_buttons.items():
            button.set_active(cat == category)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.add_css_class("launcher-apps-grid-container")

        grid = Gtk.Grid()
        grid.set_row_spacing(get_app_spacing())
        grid.set_column_spacing(get_app_spacing())
        grid.set_hexpand(True)
        grid.set_margin_start(16)
        grid.set_margin_end(16)
        grid.set_margin_top(16)
        grid.set_margin_bottom(16)

        self._app_items = []

        apps_per_row = user_options.launcher.apps_per_row if hasattr(user_options.launcher, 'apps_per_row') else 6

        for index, app in enumerate(apps):
            row = index // apps_per_row
            column = index % apps_per_row
            app_item = LauncherAppItem(app)
            if self._first_app_item is None:
                self._first_app_item = app_item
            self._app_items.append(app_item)
            grid.attach(app_item, column, row, 1, 1)

        scrolled.set_child(grid)
        self._apps_display_area.child = [scrolled]

    def get_first_app(self) -> Optional[LauncherAppItem]:
        return self._first_app_item

    def get_app_items(self) -> List[LauncherAppItem]:
        return self._app_items


class Launcher(widgets.Window):
    def __init__(self):
        self._apps_container = widgets.Box(
            vertical=True,
            visible=True,
            hexpand=True,
            vexpand=True,
            spacing=12
        )

        self._all_apps_pages = []
        self._current_page_index = 0
        self._current_search_results = []
        self._search_timeout = None

        self._entry = widgets.Entry(
            hexpand=True,
            placeholder_text="Search applications...",
            css_classes=["launcher-search"],
            on_change=self._on_search,
            on_accept=self._on_accept,
        )

        self._recent_container = RecentAppsContainer()

        self._scrolled_window = Gtk.ScrolledWindow()
        self._scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scrolled_window.set_hexpand(True)
        self._scrolled_window.set_vexpand(True)
        self._scrolled_window.set_child(self._apps_container)
        self._scrolled_window.add_css_class("launcher-content")

        main_box = widgets.Box(
            vertical=True,
            valign="start",
            halign="center",
            spacing=16,
            css_classes=["launcher"],
            hexpand=True,
            vexpand=True,
            style="min-width: 720px;",
            child=[
                widgets.Box(
                    css_classes=["launcher-search-box"],
                    spacing=12,
                    child=[
                        widgets.Icon(
                            icon_name="system-search-symbolic",
                            pixel_size=20,
                        ),
                        self._entry,
                    ],
                    hexpand=True,
                    vexpand=False,
                    valign="start",
                ),
                self._recent_container if user_options.launcher.show_recent_apps else widgets.Box(),  # Conditional display
                self._scrolled_window,
            ],
        )

        super().__init__(
            namespace="ignis_LAUNCHER",
            visible=False,
            popup=True,
            kb_mode="on_demand",
            css_classes=["unset"],
            hexpand=True,
            vexpand=True,
            setup=lambda self: self.connect("notify::visible", self._on_window_open),
            anchor=["top", "right", "bottom", "left"],
            child=widgets.Overlay(
                child=widgets.Button(
                    vexpand=True,
                    hexpand=True,
                    can_focus=False,
                    css_classes=["unset"],
                    on_click=lambda w: window_manager.close_window("ignis_LAUNCHER"),
                    style="background-color: rgba(0, 0, 0, 0.3);",
                ),
                overlays=[main_box],
            ),
        )

        self._setup_keyboard_navigation()

        self._populate_all_apps()
        self._show_all_apps_page(0)

        # Bind to option changes for reactive updates
        user_options.launcher.bind("icon_size", self._on_option_change)
        user_options.launcher.bind("apps_per_row", self._on_option_change)
        user_options.launcher.bind("show_recent_apps", self._on_option_change)
        user_options.launcher.bind("app_spacing", self._on_option_change)
        user_options.launcher.bind("show_labels", self._on_option_change)
        user_options.launcher.bind("terminal_format", self._on_option_change)

    def _perform_search(self):
        query = self._entry.text.strip().lower()
        if not query:
            self._current_search_results = []
            self._show_all_apps_page(self._current_page_index)
        else:
            results = []
            for app in applications.apps:
                # Match against name, id, or other metadata
                if query in app.name.lower() or query in getattr(app, "id", "").lower():
                    results.append(app)
            # Clamp to MAX_SEARCH_RESULTS
            results = results[:MAX_SEARCH_RESULTS]
            self._show_search_results(results)
        return False  # Prevent recurring GLib timeout

    def _on_option_change(self, *_args):
        """Rebuild UI on relevant user options changes"""
        self._populate_all_apps()
        if self._current_search_results:
            self._show_search_results(self._current_search_results)
        else:
            self._show_all_apps_page(self._current_page_index)
        self._recent_container.refresh()

    def _setup_keyboard_navigation(self):
        try:
            from gi.repository import Gdk
            controller = Gtk.EventControllerKey()
            controller.connect("key-pressed", self._on_key_pressed)
            self.add_controller(controller)
        except:
            self._entry.connect("key-press-event", self._on_entry_key_press)

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        from gi.repository import Gdk
        if keyval == Gdk.KEY_Tab:
            if len(self._apps_container.child) > 0:
                child = self._apps_container.child[0]
                if isinstance(child, CategorizedAppsPage):
                    first_app = child.get_first_app()
                    if first_app:
                        first_app.grab_focus()
                        return True
        elif keyval == Gdk.KEY_Escape:
            window_manager.close_window("ignis_LAUNCHER")
            return True
        return False

    def _on_entry_key_press(self, widget, event) -> bool:
        try:
            from gi.repository import Gdk
            keyval = event.keyval
            if keyval == Gdk.KEY_Tab:
                if len(self._apps_container.child) > 0:
                    child = self._apps_container.child[0]
                    if isinstance(child, CategorizedAppsPage):
                        first_app = child.get_first_app()
                        if first_app:
                            first_app.grab_focus()
                            return True
            elif keyval == Gdk.KEY_Escape:
                window_manager.close_window("ignis_LAUNCHER")
                return True
        except:
            pass
        return False

    def _populate_all_apps(self) -> None:
        all_apps = applications.apps
        categorizer = AppCategorizer()
        categorized = {category: [] for category in CATEGORIES.keys() if category != 'All'}

        for app in all_apps:
            try:
                categories, executable = categorizer.get_desktop_categories(app)
                category = categorizer.categorize_app(app, categories, executable)
                if category and category in categorized:
                    categorized[category].append(app)
            except Exception as e:
                print(f"Error categorizing app {app.name}: {e}")
                categorized['Utilities'].append(app)

        result = {}

        all_apps_list = []
        for apps_list in categorized.values():
            all_apps_list.extend(apps_list)

        if all_apps_list:
            result['All'] = sorted(all_apps_list, key=lambda x: x.name.lower())

        for category in sorted(categorized.keys(), key=lambda cat: CATEGORIES.get(cat, {'priority': 999})['priority']):
            if categorized[category]:
                result[category] = sorted(categorized[category], key=lambda x: x.name.lower())

        self._all_apps_pages = [result] if result else [{}]

    def _show_all_apps_page(self, page_index: int) -> None:
        if page_index < 0 or page_index >= len(self._all_apps_pages):
            return
        self._current_page_index = page_index
        categorized_page = CategorizedAppsPage(self._all_apps_pages[page_index])
        self._apps_container.child = [categorized_page]

    def _show_search_results(self, apps: List[Application]) -> None:
        self._current_search_results = apps

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)

        grid = Gtk.Grid()
        grid.set_row_spacing(get_app_spacing())
        grid.set_column_spacing(get_app_spacing())
        grid.set_hexpand(True)
        grid.set_margin_start(16)
        grid.set_margin_end(16)
        grid.set_margin_top(16)
        grid.set_margin_bottom(16)

        for index, app in enumerate(apps):
            row = index // user_options.launcher.apps_per_row
            column = index % user_options.launcher.apps_per_row
            app_item = LauncherAppItem(app)
            grid.attach(app_item, column, row, 1, 1)

        scrolled.set_child(grid)
        self._apps_container.child = [scrolled]

    def _on_window_open(self, *args) -> None:
        if not self.visible:
            return
        self._entry.text = ""
        self._entry.grab_focus()
        self._current_search_results = []
        self._show_all_apps_page(0)
        self._recent_container.refresh()

    def _on_search(self, *args) -> None:
        if self._search_timeout:
            GLib.source_remove(self._search_timeout)
        self._search_timeout = GLib.timeout_add(SEARCH_DEBOUNCE_MS, self._perform_search)

    def _on_window_close(self, *args) -> None:
        self._current_search_results.clear()
        if self._search_timeout:
            GLib.source_remove(self._search_timeout)
            self._search_timeout = None

    def _on_accept(self, *args) -> None:
        query = self._entry.text.strip()
        if self._current_search_results:
            app = self._current_search_results[0]
            if app:
                app.launch(terminal_format=get_terminal_format())
                add_recent_app(app)
                window_manager.close_window("ignis_LAUNCHER")
            return

        if len(self._apps_container.child) > 0:
            child = self._apps_container.child[0]
            if isinstance(child, CategorizedAppsPage):
                first_app = child.get_first_app()
                if first_app:
                    first_app.launch()
