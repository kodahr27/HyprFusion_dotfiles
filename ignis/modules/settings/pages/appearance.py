import os
from services.material import MaterialService
from ..elements import SwitchRow, SettingsPage, SettingsGroup, FileRow, SettingsEntry, EntryRow, SliderRow
from ignis import widgets
from user_options import user_options
from ignis.options import options

material = MaterialService.get_default()

class AppearanceEntry(SettingsEntry):
    def __init__(self):
        page = SettingsPage(
            name="Appearance",
            groups=[
                SettingsGroup(
                    name=None,
                    rows=[
                        widgets.ListBoxRow(
                            child=widgets.Picture(
                                image=options.wallpaper.bind("wallpaper_path"),
                                width=1920 // 4,
                                height=1080 // 4,
                                halign="center",
                                style="border-radius: 1rem;",
                                content_fit="cover",
                            ),
                            selectable=False,
                            activatable=False,
                        ),
                        SwitchRow(
                            label="Dark mode",
                            active=user_options.material.bind("dark_mode"),
                            on_change=lambda w, state: user_options.material.set_dark_mode(state),
                            style="margin-top: 1rem;",
                        ),
                        FileRow(
                            label="Wallpaper path",
                            button_label=os.path.basename(
                                options.wallpaper.wallpaper_path
                            )
                            if options.wallpaper.wallpaper_path
                            else None,
                            dialog=widgets.FileDialog(
                                on_file_set=lambda w, file: material.generate_colors(
                                    file.get_path()
                                ),
                                initial_path=options.wallpaper.bind("wallpaper_path"),
                                filters=[
                                    widgets.FileFilter(
                                        mime_types=["image/jpeg", "image/png"],
                                        default=True,
                                        name="Images JPEG/PNG",
                                    )
                                ],
                            ),
                        ),
                        # Launcher customization options
                        SliderRow(
                            label="Launcher Icon Size",
                            min_value=16,
                            max_value=128,
                            step_increment=4,
                            value=user_options.launcher.icon_size,
                            on_change=lambda w, val: user_options.launcher.set_icon_size(val),
                            style="margin-top: 1rem;",
                        ),
                        EntryRow(
                            label="Recording filename",
                            sublabel="Support time formatting",
                            text=options.recorder.bind("default_filename"),
                            on_change=lambda w, text: None,  # Can be updated if needed
                        ),
                        SwitchRow(
                            label="Show Recent Apps",
                            active=user_options.launcher.bind("show_recent_apps"),
                            on_change=lambda w, state: user_options.launcher.set_show_recent_apps(state),
                            style="margin-top: 1rem;",
                        ),
                        SliderRow(
                            label="Launcher App Spacing",
                            min_value=0,
                            max_value=32,
                            step_increment=1,
                            value=user_options.launcher.app_spacing,
                            on_change=lambda w, val: user_options.launcher.set_app_spacing(val),
                            style="margin-top: 1rem;",
                        ),
                        SwitchRow(
                            label="Show App Labels",
                            active=user_options.launcher.bind("show_labels"),
                            on_change=lambda w, state: user_options.launcher.set_show_labels(state),
                            style="margin-top: 1rem;",
                        ),
                        EntryRow(
                            label="Terminal Command Format",
                            sublabel="Use %command% as placeholder for application command",
                            text=user_options.launcher.bind("terminal_format"),
                            on_change=lambda w, text: None,
                            on_accept=lambda w, text: user_options.launcher.set_terminal_format(text),
                        ),
                        SliderRow(
                            label="Recent Apps Rows",
                            min_value=1,
                            max_value=12,
                            step_increment=1,
                            value=user_options.launcher.recent_apps_rows,
                            on_change=lambda w, val: user_options.launcher.set_recent_apps_rows(val),
                            style="margin-top: 1rem;",
                        ),
                        SliderRow(
                            label="Recent Apps Columns",
                            min_value=1,
                            max_value=12,
                            step_increment=1,
                            value=user_options.launcher.recent_apps_per_row,
                            on_change=lambda w, val: user_options.launcher.set_recent_apps_per_row(val),
                            style="margin-top: 1rem;",
                        ),
                        SliderRow(
                            label="Categorized Apps Columns",
                            min_value=1,
                            max_value=12,
                            step_increment=1,
                            value=user_options.launcher.apps_per_row,
                            on_change=lambda w, val: user_options.launcher.set_apps_per_row(val),
                            style="margin-top: 1rem;",
                        ),
                    ],
                )
            ],
        )
        super().__init__(
            label="Appearance",
            icon="preferences-desktop-wallpaper-symbolic",
            page=page,
        )
