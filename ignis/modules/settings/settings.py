from ignis import widgets
from user_options import user_options
from .active_page import active_page
from .pages import (
    AboutEntry,
    AppearanceEntry,
    NotificationsEntry,
    RecorderEntry,
    UserEntry,
)


from ignis import widgets
from user_options import user_options
from .active_page import active_page
from .pages import (
    AboutEntry,
    AppearanceEntry,
    NotificationsEntry,
    RecorderEntry,
    UserEntry,
)

class Settings(widgets.RegularWindow):
    def __init__(self) -> None:
        content = widgets.Box(
            hexpand=True,
            vexpand=True,
            child=active_page.bind("value", transform=lambda value: [value]),
        )
        self._listbox = widgets.ListBox()

        navigation_sidebar = widgets.Box(
            vertical=True,
            css_classes=["settings-sidebar"],
            child=[
                widgets.Label(
                    label="Settings",
                    halign="start",
                    css_classes=["settings-sidebar-label"],
                ),
                self._listbox,
            ],
        )

        super().__init__(
            title="Ignis Settings",  # Set a specific title
            default_width=1200,
            default_height=700,
            resizable=False,
            hide_on_close=True,
            visible=False,
            child=widgets.Box(child=[navigation_sidebar, content]),
            namespace="ignis_SETTINGS",
        )

        # Set window class for better identification
        self.connect("realize", self._on_realize)
        self.connect("notify::visible", self.__on_open)

    def _on_realize(self, widget):
        """Set the window class when the window is realized"""
        try:
            # Try to set a more specific window class
            if hasattr(self, 'set_wmclass'):
                self.set_wmclass("ignis-settings", "Ignis-Settings")
        except:
            pass

    def __on_open(self, *args) -> None:
        if self.visible is False:
            return

        if len(self._listbox.rows) != 0:
            return

        rows = [
            NotificationsEntry(),
            RecorderEntry(),
            AppearanceEntry(),
            UserEntry(),
            AboutEntry(),
        ]

        self._listbox.rows = rows
        self._listbox.activate_row(rows[user_options.settings.last_page])

        self._listbox.connect("row-activated", self.__update_last_page)

    def __update_last_page(self, x, row) -> None:
        user_options.settings.last_page = self._listbox.rows.index(row)