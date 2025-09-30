import os
import threading
from ignis import utils
from ignis.services.wallpaper import WallpaperService
from modules import (
    Bar,
    ControlCenter,
    Launcher,
    NotificationPopup,
    OSD,
    Powermenu,
    Settings,
)
from ignis.css_manager import CssManager, CssInfoPath
from ignis.icon_manager import IconManager
from user_options import user_options


icon_manager = IconManager.get_default()
css_manager = CssManager.get_default()
WallpaperService.get_default()

# Debounce mechanism
_css_update_timer = None
_css_update_lock = threading.Lock()

def write_user_colors_scss():
    """Write dynamic user color variables to scss/_user_colors.scss"""
    scss_colors = ""
    for key, value in user_options.material.colors.items():
        scss_colors += f"${key}: {value};\n"
    scss_colors += f"$darkmode: {str(user_options.material.dark_mode).lower()};\n"

    scss_dir = os.path.join(utils.get_current_dir(), "scss")
    if not os.path.exists(scss_dir):
        os.makedirs(scss_dir)
    colors_path = os.path.join(scss_dir, "_user_colors.scss")
    with open(colors_path, "w") as f:
        f.write(scss_colors)

def debounced_css_update():
    """Debounced CSS update to prevent infinite loops"""
    global _css_update_timer
    
    with _css_update_lock:
        if _css_update_timer:
            _css_update_timer.cancel()
        
        def update_css():
            write_user_colors_scss()
            css_manager.reload_css("main")
        
        _css_update_timer = threading.Timer(0.2, update_css)  # 200ms delay
        _css_update_timer.start()

def patch_style_scss(path: str) -> str:
    with open(path) as file:
        contents = file.read()

    # Don't call write_user_colors_scss here to avoid loops
    # It should be called before this function is triggered
    return utils.sass_compile(
        string=contents, extra_args=["--load-path", utils.get_current_dir()]
    )

# Initial write of user colors
write_user_colors_scss()

css_manager.apply_css(
    CssInfoPath(
        name="main",
        path=os.path.join(utils.get_current_dir(), "style.scss"),
        compiler_function=patch_style_scss,
    )
)

# Connect to material color changes with debouncing
user_options.material.connect("changed", lambda *args: debounced_css_update())

icon_manager.add_icons(os.path.join(utils.get_current_dir(), "icons"))

utils.exec_sh("gsettings set org.gnome.desktop.interface gtk-theme Material")
utils.exec_sh("gsettings set org.gnome.desktop.interface icon-theme Papirus")
utils.exec_sh(
    'gsettings set org.gnome.desktop.interface font-name "JetBrains Mono Regular 11"'
)
utils.exec_sh("hyprctl reload")

ControlCenter()

for monitor in range(utils.get_n_monitors()):
    Bar(monitor)

for monitor in range(utils.get_n_monitors()):
    NotificationPopup(monitor)

Launcher()
Powermenu()
OSD()
Settings()