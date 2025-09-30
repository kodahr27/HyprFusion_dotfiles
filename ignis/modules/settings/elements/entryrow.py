from ignis import widgets
from .row import SettingsRow  # Import the base SettingsRow class
from gi.repository import Gtk


class EntryRow(SettingsRow):
    def __init__(self, label: str, text: str, on_change, on_accept=None, sublabel: str = None, entry_width=150, **kwargs):
        super().__init__(label=label, sublabel=sublabel, **kwargs)

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hbox.set_hexpand(True)
        hbox.set_halign(Gtk.Align.FILL)

        # Create a spacer that expands and pushes the entry to the right
        spacer = Gtk.Box()
        spacer.set_hexpand(True)

        self._entry = widgets.Entry(text=text)
        self._entry.set_size_request(entry_width, -1)

        self._entry.connect("changed", self._on_text_changed)
        if on_accept:
            self._entry.connect("activate", self._on_text_accepted)
        else:
            self._on_text_accepted = None

        hbox.append(spacer)  # Spacer expands in the middle
        hbox.append(self._entry)  # Entry sticks to the right

        self.child.append(hbox)

        self._external_on_change = on_change
        self._external_on_accept = on_accept

    def _on_text_changed(self, entry):
        if self._external_on_change:
            self._external_on_change(entry, entry.text)

    def _on_text_accepted(self, entry):
        if self._external_on_accept:
            self._external_on_accept(entry, entry.text)
