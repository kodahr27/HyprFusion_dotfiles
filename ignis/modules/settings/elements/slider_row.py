from gi.repository import Gtk
from ignis import widgets
from .row import SettingsRow  # Import SettingsRow
from typing import Callable
from ignis.gobject import Binding


class SliderRow(SettingsRow):
    def __init__(
        self,
        min_value: int,
        max_value: int,
        step_increment: int,
        value: int | Binding,
        on_change: Callable[[Gtk.Scale, int], None],
        label: str = None,
        sublabel: str = None,
        slider_width: int = 260,
        **kwargs,
    ):
        # Build SettingsRow with label + sublabel
        super().__init__(label=label, sublabel=sublabel, **kwargs)

        # Adjustment
        adjustment = Gtk.Adjustment.new(
            value if not isinstance(value, Binding) else value.value,
            min_value,
            max_value,
            step_increment,
            step_increment * 10,
            0,
        )

        # Slider
        self._scale = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL,
            adjustment=adjustment,
        )
        self._scale.set_digits(0)
        self._scale.set_draw_value(True)
        self._scale.set_size_request(slider_width, -1)
        self._scale.set_halign(Gtk.Align.END)
        self._scale.set_valign(Gtk.Align.CENTER)

        self._scale.connect("value-changed", self._on_value_changed)

        if isinstance(value, Binding):
            value.bind_property("value", self._scale, "value")

        # Ensure slider is pushed to right
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        self.child.append(spacer)
        self.child.append(self._scale)

        self._external_on_change = on_change

    def _on_value_changed(self, scale: Gtk.Scale) -> None:
        val = int(scale.get_value())
        if self._external_on_change:
            self._external_on_change(scale, val)

    def set_value(self, value: int) -> None:
        self._scale.set_value(value)

    def get_value(self) -> int:
        return int(self._scale.get_value())
