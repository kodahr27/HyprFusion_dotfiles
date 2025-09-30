from gi.repository import Gtk, GLib, Gdk
from ignis import widgets
from .widgets import StatusPill, Tray, KeyboardLayout, Battery, Workspaces, Apps, RunningApps
import os

class Bar(widgets.Window):
    __gtype_name__ = "Bar"

    def __init__(self, monitor: int):
        center_box = widgets.Box()
        center_box.append(Apps())         # Pinned apps
        center_box.append(RunningApps())  # Running apps

        start_widget = widgets.Box()
        start_widget.append(Workspaces())

        end_widget = widgets.Box()
        for ch in [Tray(), KeyboardLayout(), Battery(), StatusPill(monitor)]:
            end_widget.append(ch)

        super().__init__(
            anchor=["left", "top", "right"],
            exclusivity="exclusive",
            monitor=monitor,
            namespace=f"ignis_BAR_{monitor}",
            layer="top",
            kb_mode="none",
            child=widgets.CenterBox(
                css_classes=["bar-widget"],
                start_widget=start_widget,
                center_widget=center_box,
                end_widget=end_widget,
            ),
            css_classes=["unset"],
        )

    def get_window(self):
        gdk_win = super().get_window()
        if gdk_win is None:
            toplevel = self.get_toplevel()
            if toplevel and toplevel != self:
                return toplevel.get_window()
        return gdk_win

    def get_toplevel(self):
        return self
