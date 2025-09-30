import os
from ignis.options_manager import OptionsGroup, OptionsManager
from ignis import DATA_DIR, CACHE_DIR  # type: ignore

USER_OPTIONS_FILE = f"{DATA_DIR}/user_options.json"
OLD_USER_OPTIONS_FILE = f"{CACHE_DIR}/user_options.json"


# FIXME: remove someday
def _migrate_old_user_options():
    with open(OLD_USER_OPTIONS_FILE) as f:
        data = f.read()
    with open(USER_OPTIONS_FILE, "w") as f:
        f.write(data)


class UserOptions(OptionsManager):
    def __init__(self):
        if not os.path.exists(USER_OPTIONS_FILE) and os.path.exists(OLD_USER_OPTIONS_FILE):
            _migrate_old_user_options()

        try:
            super().__init__(file=USER_OPTIONS_FILE)
        except FileNotFoundError:
            pass

        # --- ADDED: Patch color defaults to avoid undefined SASS variables ---
        if hasattr(self, "material"):
            defaults = {
                "surface": "#1a1112",
                "background": "#1a1112",
                "primary": "#ffb2bc",
                "secondary": "#e5bdc0",
                "tertiary": "#eabf8f",
                # Add all other required keys as needed
            }
            for key, value in defaults.items():
                if key not in self.material.colors:
                    self.material.colors[key] = value

    class User(OptionsGroup):
        avatar: str = f"/var/lib/AccountsService/icons/{os.getenv('USER')}"

    class Settings(OptionsGroup):
        last_page: int = 0

    class Material(OptionsGroup):
        dark_mode: bool = True
        colors: dict[str, str] = {}
        # Accent color option removed here

    class Launcher(OptionsGroup):
        icon_size: int = 48
        show_recent_apps: bool = True
        app_spacing: int = 8       # Spacing between launcher apps
        show_labels: bool = True   # Show app labels
        recent_apps_per_row: int = 6          # Number of columns in the recent apps
        recent_apps_rows: int = 2       # Example: rows to display in recent apps
        apps_per_row: int = 6          # Number of columns in the app grid
        terminal_format: str = "kitty %command%"

    user = User()
    settings = Settings()
    material = Material()
    launcher = Launcher()


user_options = UserOptions()
