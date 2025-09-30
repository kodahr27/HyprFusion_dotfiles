import os
import re
import subprocess
import logging
from glob import glob
from configparser import ConfigParser
from typing import Optional

logger = logging.getLogger("IconManager")


class IconManager:
    """XDG spec-compliant Icon manager with DE theme detection and improved caching."""

    ICON_BASE_PATHS = []
    PIXMAPS_PATH = "/usr/share/pixmaps"

    DESKTOP_FILES_PATHS = [
        os.path.expanduser("~/.local/share/applications"),
        "/usr/share/applications",
    ]

    _desktop_files_indexed = False
    _desktop_files_index = {}

    _icon_files_index = {}  # theme_name -> {icon_name: icon_path}
    _icon_cache = {}       # Cache icon_name or desktop_file -> icon_path or None
    _desktop_cache = {}    # Cache app_name_lower -> desktop_file_path or None
    _app_icon_cache = {}   # Cache (app_name, class_name) -> icon_path or None

    _current_theme = None

    # --- Icon theme detection section ---

    @classmethod
    def _detect_gnome_theme(cls) -> Optional[str]:
        """Detect GNOME icon theme using gsettings."""
        try:
            out = subprocess.check_output(
                ["gsettings", "get", "org.gnome.desktop.interface", "icon-theme"],
                text=True
            ).strip()
            if out and out not in ("", "''", '""'):
                theme = out.strip("'\"")
                return theme
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            return None
        return None

    @classmethod
    def _detect_kde_theme(cls) -> Optional[str]:
        """Detect KDE icon theme from kdeglobals."""
        kdeglobals = os.path.expanduser("~/.config/kdeglobals")
        if os.path.exists(kdeglobals):
            parser = ConfigParser()
            parser.read(kdeglobals)
            try:
                return parser.get("Icons", "Theme")
            except Exception:
                return None
        return None

    @classmethod
    def _detect_xfce_theme(cls) -> Optional[str]:
        """Detect XFCE icon theme from xfconf."""
        try:
            out = subprocess.check_output(
                ["xfconf-query", "-c", "xsettings", "-p", "/Net/IconThemeName"],
                text=True
            ).strip()
            return out if out else None
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            return None

    @classmethod
    def _detect_gtk_theme(cls) -> Optional[str]:
        """Detect GTK icon theme from gtk-3.0 settings.ini or gtk-4.0/settings.ini."""
        for gtk_ver in ("3.0", "4.0"):
            gtk_config = os.path.expanduser(f"~/.config/gtk-{gtk_ver}/settings.ini")
            if os.path.exists(gtk_config):
                parser = ConfigParser()
                parser.read(gtk_config)
                try:
                    return parser.get("Settings", "gtk-icon-theme-name")
                except Exception:
                    continue
        return None

    @classmethod
    def _detect_current_theme(cls) -> str:
        """Detect current icon theme, cache it, use cross-DE detection."""
        if cls._current_theme:
            return cls._current_theme

        theme = (
            cls._detect_gnome_theme()
            or cls._detect_kde_theme()
            or cls._detect_xfce_theme()
            or cls._detect_gtk_theme()
            or "hicolor"
        )
        cls._current_theme = theme
        logger.debug(f"Detected current icon theme: {theme}")
        return theme

    # --- Indexing and caching logic ---

    @classmethod
    def _init_base_paths(cls):
        """Initialize base icon paths from XDG spec environment."""
        if cls.ICON_BASE_PATHS:
            return
        xdg_data_home = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
        data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
        cls.ICON_BASE_PATHS.append(os.path.join(xdg_data_home, "icons"))
        for d in data_dirs:
            cls.ICON_BASE_PATHS.append(os.path.join(d, "icons"))
        cls.ICON_BASE_PATHS.append(cls.PIXMAPS_PATH)

    @classmethod
    def _index_desktop_files(cls):
        if cls._desktop_files_indexed:
            return
        index = {}
        for apps_dir in cls.DESKTOP_FILES_PATHS:
            if not os.path.isdir(apps_dir):
                continue
            for desktop_path in glob(os.path.join(apps_dir, "*.desktop")):
                try:
                    with open(desktop_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        names = re.findall(r"^Name(?:\[[^\]]+\])?=(.+)$", content, re.MULTILINE)
                        for name in names:
                            key = name.strip().lower()
                            if key not in index:
                                index[key] = desktop_path
                except Exception as e:
                    logger.debug(f"Error reading desktop file {desktop_path}: {e}")
        cls._desktop_files_index = index
        cls._desktop_files_indexed = True
        logger.debug(f"Indexed {len(index)} desktop files")

    @classmethod
    def _index_icon_files(cls, theme: str):
        cls._init_base_paths()
        if theme in cls._icon_files_index:
            return

        index = {}
        search_themes = [theme]
        if theme != "hicolor":
            search_themes.append("hicolor")

        for base_dir in cls.ICON_BASE_PATHS:
            for theme_name in search_themes:
                theme_dir = os.path.join(base_dir, theme_name)
                if not os.path.isdir(theme_dir):
                    continue
                for root, _, files in os.walk(theme_dir):
                    for file in files:
                        base, ext = os.path.splitext(file)
                        ext = ext.lower()
                        if ext in (".png", ".svg", ".xpm") and base not in index:
                            index[base] = os.path.join(root, file)

        if os.path.isdir(cls.PIXMAPS_PATH):
            for root, _, files in os.walk(cls.PIXMAPS_PATH):
                for file in files:
                    base, ext = os.path.splitext(file)
                    if ext.lower() in (".png", ".svg", ".xpm") and base not in index:
                        index[base] = os.path.join(root, file)

        cls._icon_files_index[theme] = index
        logger.debug(f"Indexed {len(index)} icons for theme {theme}")

    @classmethod
    def find_desktop_file_by_name(cls, name: str) -> Optional[str]:
        if not name:
            return None
        key = name.lower()
        if key in cls._desktop_cache:
            return cls._desktop_cache[key]

        cls._index_desktop_files()
        desktop_path = cls._desktop_files_index.get(key)
        cls._desktop_cache[key] = desktop_path
        return desktop_path

    @classmethod
    def find_icon_for_desktop(cls, desktop_file: str) -> Optional[str]:
        if not desktop_file or not os.path.exists(desktop_file):
            return None
        if desktop_file in cls._icon_cache:
            return cls._icon_cache[desktop_file]

        try:
            with open(desktop_file, "r", encoding="utf-8") as f:
                content = f.read()
                match = re.search(r"^Icon=(.+)$", content, re.MULTILINE)
                if not match:
                    cls._icon_cache[desktop_file] = None
                    return None
                icon_name = match.group(1).strip()
                if os.path.isabs(icon_name) and os.path.exists(icon_name):
                    cls._icon_cache[desktop_file] = icon_name
                    return icon_name
                icon_path = cls.find_icon_by_name(icon_name)
                cls._icon_cache[desktop_file] = icon_path
                return icon_path
        except Exception as e:
            logger.debug(f"Error reading desktop file {desktop_file}: {e}")
            cls._icon_cache[desktop_file] = None
            return None

    @classmethod
    def find_icon_by_name(cls, icon_name: str) -> Optional[str]:
        if not icon_name:
            return None
        if icon_name in cls._icon_cache:
            return cls._icon_cache[icon_name]

        theme = cls._detect_current_theme()
        cls._index_icon_files(theme)
        candidates = cls._icon_files_index.get(theme, {})

        icon_path = candidates.get(icon_name)
        if not icon_path:
            for ext in (".png", ".svg", ".xpm"):
                icon_path = candidates.get(icon_name + ext)
                if icon_path:
                    break

        cls._icon_cache[icon_name] = icon_path
        return icon_path

    @classmethod
    def get_icon_for_app(cls, app_name: str = None, class_name: str = None) -> Optional[str]:
        cache_key = (app_name.lower() if app_name else None,
                     class_name.lower() if class_name else None)
        if cache_key in cls._app_icon_cache:
            return cls._app_icon_cache[cache_key]

        icon = None
        if app_name:
            desktop_file = cls.find_desktop_file_by_name(app_name)
            if desktop_file:
                icon = cls.find_icon_for_desktop(desktop_file)

        if not icon and class_name:
            icon = cls.find_icon_by_name(class_name)

        cls._app_icon_cache[cache_key] = icon
        return icon

    @classmethod
    def clear_cache(cls):
        cls._desktop_cache.clear()
        cls._icon_cache.clear()
        cls._app_icon_cache.clear()
        cls._desktop_files_indexed = False
        cls._desktop_files_index.clear()
        cls._icon_files_index.clear()
        cls._current_theme = None
        logger.debug("Cleared all IconManager caches and indexes")
