from __future__ import annotations

import asyncio
from datetime import date, datetime
from functools import partial

import flet as ft
import flet_geolocator as ftg

from models import Checkpoint, CheckpointRepository, build_zip_backup, map_link


class CheckpointView:
    STOP_DURATION_OPTIONS = {
        "3": 3 * 60,
        "5": 5 * 60,
        "10": 10 * 60,
        "15": 15 * 60,
    }
    DEFAULT_STOP_DURATION = "5"
    STOP_SPEED_METERS_PER_SECOND = 1.0
    THEME_MODES = {
        "system": ft.ThemeMode.SYSTEM,
        "light": ft.ThemeMode.LIGHT,
        "dark": ft.ThemeMode.DARK,
    }
    HISTORY_LOADING_DELAY_SECONDS = 0.4

    def __init__(self, page: ft.Page, repository: CheckpointRepository):
        self._page = page
        self._repository = repository
        self._tracker_enabled = False
        self._still_since: datetime | None = None
        self._last_position: ftg.GeolocatorPosition | None = None
        self._last_auto_checkpoint_at: datetime | None = None
        self._stop_seconds = self.STOP_DURATION_OPTIONS[self.DEFAULT_STOP_DURATION]

        self._filter_from: date | None = None
        self._filter_to: date | None = None
        self._filter_search: str = ""
        self._displayed_checkpoints: list[Checkpoint] = []

        geolocator_kwargs = {
            "configuration": ftg.GeolocatorConfiguration(
                accuracy=ftg.GeolocatorPositionAccuracy.HIGH,
                distance_filter=0,
            ),
            "on_position_change": self._on_position_change,
            "on_error": self._on_location_error,
        }
        if hasattr(ftg, "GeolocatorAndroidSettings"):
            geolocator_kwargs["android_configuration"] = ftg.GeolocatorAndroidSettings(
                foreground_notification_title="Pynal Destination",
                foreground_notification_text="Tracking your location for stop detection...",
                foreground_notification_set_ongoing=True,
                foreground_notification_enable_wake_lock=True,
                foreground_notification_enable_wifi_lock=True,
            )
        self._geolocator = ftg.Geolocator(**geolocator_kwargs)

        self._file_picker = ft.FilePicker()
        self._url_launcher = ft.UrlLauncher()
        self._date_range_picker = ft.DateRangePicker(
            help_text="Filter by date(s) — pick one day, or a start and end",
            on_change=self._on_date_range_picked,
        )
        self._page.services.extend([self._geolocator, self._file_picker, self._url_launcher])

        self._tracking_switch = ft.Switch(label="Automatic stop detection", on_change=self._toggle_tracking)

        self._status_icon = ft.Icon(ft.Icons.INFO, size=20)
        self._status_text = ft.Text("Automatic detection is paused.", text_align=ft.TextAlign.CENTER)
        self._status_row = ft.Row(
            alignment=ft.MainAxisAlignment.CENTER,
            controls=[self._status_icon, self._status_text],
        )

        self._stop_duration_display = ft.Text(
            f"Stop detection duration: {self._stop_seconds // 60} minutes\n(adjust in Settings)",
            text_align=ft.TextAlign.CENTER,
        )

        self._note = ft.TextField(label="Optional note for the checkpoint")
        self._keep_note = ft.Checkbox(label="Keep note after saving", value=False)

        self._search_field = ft.TextField(
            label="Search notes",
            dense=True,
            on_change=self._on_search_change,
            width=220,
        )
        self._filter_summary = ft.Text(
            "Showing all checkpoints.",
            text_align=ft.TextAlign.CENTER,
            weight=ft.FontWeight.BOLD,
        )
        self._history_progress = ft.ProgressBar(width=280, visible=False)
        self._history_loading_text = ft.Text("Loading checkpoints…", visible=False)
        self._history = ft.ListView(expand=True)

        self._export_json_button = ft.Button(
            content="Export JSON",
            icon=ft.Icons.FILE_DOWNLOAD,
            on_click=self._export_json,
            style=ft.ButtonStyle(
                color=ft.Colors.ON_PRIMARY,
                bgcolor=ft.Colors.PRIMARY,
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=10,
            ),
        )
        self._export_markdown_button = ft.Button(
            content="Export Markdown",
            icon=ft.Icons.DESCRIPTION,
            on_click=self._export_markdown,
            style=ft.ButtonStyle(
                color=ft.Colors.ON_PRIMARY,
                bgcolor=ft.Colors.PRIMARY,
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=10,
            ),
        )
        self._export_progress = ft.ProgressBar(width=280, visible=False)
        self._export_status = ft.Text("", visible=False)

        self._clear_progress = ft.ProgressBar(width=280, visible=False)
        self._clear_status = ft.Text("", visible=False)
        self._clear_dialog = ft.AlertDialog(
            title=ft.Text("Clear all history?"),
            content=ft.Column(
                tight=True,
                controls=[
                    ft.Text("This permanently deletes every checkpoint saved on this device. This cannot be undone."),
                    self._clear_progress,
                    self._clear_status,
                ],
            ),
            actions=[
                ft.TextButton(content="Cancel", on_click=lambda _event: self._page.pop_dialog()),
                ft.TextButton(content="Export backup, then clear", on_click=self._backup_and_clear),
                ft.TextButton(content="Clear without backup", on_click=self._clear_without_backup),
            ],
        )

        self._theme_selector = ft.RadioGroup(
            value="system",
            on_change=self._change_theme,
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
                controls=[
                    ft.Radio(value="system", label="Use system setting"),
                    ft.Radio(value="light", label="Always use light mode"),
                    ft.Radio(value="dark", label="Always use dark mode"),
                ],
            ),
        )

        self._stop_duration_selector = ft.RadioGroup(
            value=self.DEFAULT_STOP_DURATION,
            on_change=self._change_stop_duration,
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
                controls=[
                    ft.Radio(value="3", label="3 minutes — busy city driving"),
                    ft.Radio(value="5", label="5 minutes — recommended default"),
                    ft.Radio(value="10", label="10 minutes — highway / long drives"),
                    ft.Radio(value="15", label="15 minutes — only longer stops"),
                ],
            ),
        )

        self._tabs = ft.Tabs(
            length=3,
            expand=True,
            content=ft.Column(
                expand=True,
                controls=[
                    ft.TabBar(
                        tab_alignment=ft.TabAlignment.CENTER,
                        tabs=[
                            ft.Tab(label="Record", icon=ft.Icons.LOCATION_ON),
                            ft.Tab(label="History", icon=ft.Icons.MANAGE_HISTORY),
                            ft.Tab(label="Settings", icon=ft.Icons.SETTINGS),
                        ],
                    ),
                    ft.TabBarView(
                        expand=True,
                        controls=[
                            self._record_panel(),
                            self._history_panel(),
                            self._settings_panel(),
                        ],
                    ),
                ],
            ),
        )

        self._stop_check_task = None

    async def initialize(self) -> None:
        self._repository.initialize()
        saved_mode = self._repository.get_setting("theme_mode", "system")
        selected_mode = saved_mode if saved_mode in self.THEME_MODES else "system"
        self._theme_selector.value = selected_mode
        self._page.theme_mode = self.THEME_MODES[selected_mode]

        saved_stop_duration = self._repository.get_setting("stop_duration_minutes", self.DEFAULT_STOP_DURATION)
        selected_stop_duration = (
            saved_stop_duration if saved_stop_duration in self.STOP_DURATION_OPTIONS else self.DEFAULT_STOP_DURATION
        )
        self._stop_duration_selector.value = selected_stop_duration
        self._stop_seconds = self.STOP_DURATION_OPTIONS[selected_stop_duration]
        self._update_stop_duration_display()

        await self._update_permission_status()
        await self._refresh_history()
        self._stop_check_task = asyncio.create_task(self._periodic_stop_check())

    def control(self) -> ft.Control:
        return ft.SafeArea(content=self._tabs, expand=True)

    # ---------- Periodic checker ----------
    async def _periodic_stop_check(self) -> None:
        while True:
            await asyncio.sleep(5)
            if not self._tracker_enabled:
                continue

            now = datetime.now().astimezone()
            need_fresh = (
                self._last_position is None
                or (now - self._last_position.timestamp).total_seconds() > 10
            )
            if need_fresh:
                try:
                    position = await asyncio.wait_for(
                        self._geolocator.get_current_position(),
                        timeout=5.0
                    )
                    self._last_position = position
                except Exception:
                    pass

            if self._last_position is None:
                continue

            speed = self._last_position.speed or 0.0
            if speed <= self.STOP_SPEED_METERS_PER_SECOND:
                if self._still_since is None:
                    self._still_since = now
                    self._set_status("Stillness detected;\nmonitoring for the stop duration to pass.")
                else:
                    elapsed = (now - self._still_since).total_seconds()
                    if elapsed >= self._stop_seconds and self._can_record_auto(now):
                        await self._save_position(self._last_position, "Automatic stop")
                        self._last_auto_checkpoint_at = now
                        self._still_since = None
                        self._set_status("Stop recorded. Stillness continues;\nwill record again after the duration.")
            else:
                if self._still_since is not None:
                    self._set_status("Movement detected;\nmonitoring for the next long pause.")
                self._still_since = None
    # ----------------------------------------------------------------

    def _record_panel(self) -> ft.Control:
        header = ft.Container(
            content=ft.Text(
                "Save a stop now, or allow the app to save a checkpoint after you've"
                " been still for a while.",
                text_align=ft.TextAlign.CENTER,
                weight=ft.FontWeight.BOLD,
            ),
            padding=10,
            bgcolor=ft.Colors.SURFACE,
            width=float("inf"),
        )
        header_divider = ft.Divider(height=1, thickness=1)

        footer = ft.Container(
            content=ft.Text(
                "Location history stays on this device.\n"
                "Background tracking depends on the location permission you grant and your\n"
                " phone's battery settings.",
                text_align=ft.TextAlign.CENTER,
                weight=ft.FontWeight.BOLD,
            ),
            padding=10,
            bgcolor=ft.Colors.SURFACE,
            width=float("inf"),
        )
        footer_divider = ft.Divider(height=1, thickness=1)

        record_button = ft.Button(
            content="Record current stop",
            icon=ft.Icons.LOCATION_ON,
            on_click=self._record_manual,
            width=200,
            height=50,
            style=ft.ButtonStyle(
                color=ft.Colors.ON_PRIMARY,
                bgcolor=ft.Colors.PRIMARY,
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=12,
            ),
        )

        middle = ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=20,
            alignment=ft.MainAxisAlignment.CENTER,
            controls=[
                self._tracking_switch,
                self._status_row,
                ft.Row(
                    alignment=ft.MainAxisAlignment.CENTER,
                    controls=[
                        ft.Icon(ft.Icons.TIMER, size=20),
                        self._stop_duration_display,
                    ]
                ),
                self._note,
                ft.Row(
                    alignment=ft.MainAxisAlignment.CENTER,
                    controls=[self._keep_note],
                ),
                record_button,
            ],
        )

        return ft.Container(
            content=ft.Column(
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=0,
                controls=[
                    header,
                    header_divider,
                    ft.Container(
                        content=middle,
                        expand=True,
                        padding=10,
                    ),
                    footer_divider,
                    footer,
                ],
            ),
            expand=True,
        )

    def _history_panel(self) -> ft.Control:
        pick_date_button = ft.Button(
            content="Pick date(s)",
            icon=ft.Icons.DATE_RANGE,
            on_click=lambda _event: self._page.show_dialog(self._date_range_picker),
            style=ft.ButtonStyle(
                color=ft.Colors.ON_PRIMARY,
                bgcolor=ft.Colors.PRIMARY,
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=10,
            ),
        )
        clear_filters_button = ft.Button(
            content="Clear filters",
            icon=ft.Icons.CLEAR,
            on_click=self._clear_filters,
            style=ft.ButtonStyle(
                color=ft.Colors.ERROR,
                bgcolor=None,
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=10,
            ),
        )
        refresh_button = ft.IconButton(
            icon=ft.Icons.REFRESH,
            on_click=self._refresh_history,
            tooltip="Refresh history",
            icon_color=ft.Colors.PRIMARY,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=8,
                bgcolor=ft.Colors.SURFACE,
            ),
        )
        hint_text = ft.Text(
            "Tap the ↗ icon on a checkpoint\n"
            "to open it in OpenStreetMap.",
            text_align=ft.TextAlign.CENTER,
        )

        return ft.Container(
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
                scroll=ft.ScrollMode.ALWAYS,
                controls=[
                    ft.Text("Export", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=20,
                        controls=[
                            self._export_markdown_button,
                            self._export_json_button,
                        ],
                    ),
                    ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[self._export_progress]),
                    ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[self._export_status]),
                    ft.Divider(),
                    ft.Text("Filters", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        wrap=True,
                        controls=[
                            refresh_button,
                            self._search_field,
                            pick_date_button,
                            clear_filters_button,
                        ],
                    ),
                    hint_text,
                    self._filter_summary,
                    ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[self._history_progress]),
                    ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[self._history_loading_text]),
                    self._history,
                ],
            ),
            padding=10,
            expand=True,
        )

    def _settings_panel(self) -> ft.Control:
        clear_button = ft.Button(
            content="Clear history",
            icon=ft.Icons.DELETE_FOREVER,
            on_click=self._confirm_clear_history,
            style=ft.ButtonStyle(
                color=ft.Colors.ON_ERROR,
                bgcolor=ft.Colors.ERROR,
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=10,
            ),
        )

        return ft.Container(
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=20,
                scroll=ft.ScrollMode.ALWAYS,
                controls=[
                    ft.Text("Appearance", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                    ft.Text(
                        "Choose light mode, dark mode,\nor follow your device setting.",
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        controls=[self._theme_selector],
                    ),
                    ft.Divider(),
                    ft.Text("Stop detection", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                    ft.Text(
                        "How long you must stay still before a\n"
                        "checkpoint saves automatically. Shorter\ncatches quick stops but may trigger\nat traffic lights;"
                        " longer only catches\nlonger stops.",
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        controls=[self._stop_duration_selector],
                    ),
                    ft.Divider(),
                    ft.Text("Danger zone", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                    ft.Text(
                        "Permanently delete every checkpoint\nsaved on this device.",
                        text_align=ft.TextAlign.CENTER,
                    ),
                    clear_button,
                ],
            ),
            padding=10,
            expand=True,
        )

    def _change_theme(self, _event) -> None:
        selected_mode = self._theme_selector.value or "system"
        self._page.theme_mode = self.THEME_MODES[selected_mode]
        self._repository.set_setting("theme_mode", selected_mode)
        self._page.update()

    def _change_stop_duration(self, _event) -> None:
        selected = self._stop_duration_selector.value or self.DEFAULT_STOP_DURATION
        self._stop_seconds = self.STOP_DURATION_OPTIONS.get(
            selected, self.STOP_DURATION_OPTIONS[self.DEFAULT_STOP_DURATION]
        )
        self._repository.set_setting("stop_duration_minutes", selected)
        self._update_stop_duration_display()
        self._page.update()

    def _update_stop_duration_display(self) -> None:
        self._stop_duration_display.value = (
            f"Stop detection duration: {self._stop_seconds // 60} minutes\n(adjust in Settings)"
        )

    def _set_status(self, message: str) -> None:
        self._status_text.value = message
        if "paused" in message.lower():
            icon = ft.Icons.PAUSE_CIRCLE
        elif "detecting" in message.lower() or "stillness" in message.lower() or "updated" in message.lower():
            icon = ft.Icons.PLAY_CIRCLE
        elif "movement detected" in message.lower():
            icon = ft.Icons.DIRECTIONS_WALK
        elif "permission denied" in message.lower() or "permission" in message.lower():
            icon = ft.Icons.WARNING
        elif "could not get location" in message.lower() or "timed out" in message.lower():
            icon = ft.Icons.ERROR
        elif "location updates are unavailable" in message.lower():
            icon = ft.Icons.SIGNAL_WIFI_OFF
        elif "saved" in message.lower():
            icon = ft.Icons.CHECK_CIRCLE
        else:
            icon = ft.Icons.INFO
        self._status_icon.name = icon
        self._page.update()

    # ---- Battery settings helper (used by prompt) ----
    async def _open_battery_settings(self, _event) -> None:
        if self._page.platform.name != "ANDROID":
            self._set_status("Battery optimisation settings are only available on Android.")
            self._page.update()
            return
        await self._url_launcher.launch_url("android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS")

    # ---- Battery prompt on toggle ----
    async def _prompt_battery_optimization(self) -> None:
        """Show a dialog asking the user to exempt from battery optimisation (Android only)."""
        if self._page.platform.name != "ANDROID":
            return
        dialog = ft.AlertDialog(
            title=ft.Text("Battery optimisation"),
            content=ft.Text(
                "For reliable background tracking, please exempt this app from battery optimisation.\n\n"
                "Tap 'Open settings' to exempt, or 'Continue anyway' to start tracking (may be less reliable)."
            ),
            actions=[
                ft.TextButton(content="Continue anyway", on_click=lambda e: self._page.pop_dialog()),
                ft.TextButton(
                    content="Open settings",
                    on_click=lambda e: self._page.run_task(self._open_battery_settings_from_dialog, e),
                ),
            ],
        )
        self._page.show_dialog(dialog)

    async def _open_battery_settings_from_dialog(self, _event) -> None:
        self._page.pop_dialog()
        await self._open_battery_settings(_event)

    # ----------------------------------------------------------------

    async def _update_permission_status(self) -> None:
        platform_name = self._page.platform.name
        if platform_name in ("WEB", "IOS", "BROWSER"):
            self._set_status(
                "Automatic detection works best while the app is in focus.\n"
                "Background tracking is limited on this platform."
            )
            return
        try:
            status = await self._geolocator.get_permission_status()
        except (AttributeError, NotImplementedError):
            status = None
        if status in (ftg.GeolocatorPermissionStatus.ALWAYS, ftg.GeolocatorPermissionStatus.WHILE_IN_USE):
            if status == ftg.GeolocatorPermissionStatus.ALWAYS:
                self._set_status(
                    "Automatic detection is paused.\nTap the switch to start (works in background)."
                )
            else:
                self._set_status(
                    "Automatic detection is paused.\nTap the switch to start (best when app is focused)."
                )
        else:
            self._set_status(
                "Automatic detection is paused.\n"
                "Tap the switch to grant location permission\n"
                "(background tracking requires 'Always allow')."
            )

    async def _toggle_tracking(self, _event) -> None:
        if self._tracking_switch.value:
            permission = await self._geolocator.request_permission()
            if permission not in (ftg.GeolocatorPermissionStatus.ALWAYS, ftg.GeolocatorPermissionStatus.WHILE_IN_USE):
                self._tracking_switch.value = False
                self._tracker_enabled = False
                self._set_status(
                    "Location permission denied.\nAutomatic detection is paused.\nGrant permission in system settings."
                )
                self._page.update()
                return
            # Permission granted – enable tracking
            self._tracker_enabled = True
            if permission == ftg.GeolocatorPermissionStatus.ALWAYS:
                self._set_status(
                    "Detecting long pauses while\nlocation updates are available.\n(Background allowed)."
                )
            else:
                self._set_status(
                    "Detecting long pauses while\nlocation updates are available.\n(Best when app is focused)."
                )
            platform_name = self._page.platform.name
            if platform_name in ("WEB", "IOS", "BROWSER"):
                self._set_status(self._status_text.value + "\n(Works only while the app is in focus.)")
            # Prompt battery optimisation (Android only)
            if platform_name == "ANDROID":
                await self._prompt_battery_optimization()
        else:
            self._tracker_enabled = False
            self._still_since = None
            self._set_status("Automatic detection is paused.")
        self._page.update()

    async def _record_manual(self, _event) -> None:
        try:
            position = await self._geolocator.get_current_position()
            await self._save_position(position, "Manual")
        except Exception as e:
            self._set_status(f"Could not get location: {e}.\nPlease check your GPS/signal and try again.")

    async def _on_position_change(self, event: ftg.GeolocatorPositionChangeEvent) -> None:
        self._last_position = event.position
        if self._tracker_enabled:
            speed = event.position.speed or 0.0
            if speed <= self.STOP_SPEED_METERS_PER_SECOND:
                self._set_status("Stillness detected;\nmonitoring for the stop duration to pass.")
            else:
                self._set_status("Movement detected;\nmonitoring for the next long pause.")

    async def _save_position(self, position: ftg.GeolocatorPosition, source: str) -> None:
        if position.latitude is None or position.longitude is None:
            self._set_status("The device did not provide a usable coordinate.")
            return
        checkpoint = self._repository.add(
            float(position.latitude),
            float(position.longitude),
            source,
            self._note.value,
        )
        if not self._keep_note.value:
            self._note.value = ""
        self._set_status(f"{source} checkpoint saved at {checkpoint.coordinate_text}.")
        await self._refresh_history()

    def _can_record_auto(self, now: datetime) -> bool:
        return self._last_auto_checkpoint_at is None or (now - self._last_auto_checkpoint_at).total_seconds() >= self._stop_seconds

    def _on_location_error(self, _event) -> None:
        self._set_status("Location updates are unavailable.\nCheck Location Services and permissions.")

    # --- History filtering -------------------------------------------------

    async def _on_date_range_picked(self, _event) -> None:
        start = self._date_range_picker.start_value
        end = self._date_range_picker.end_value
        local_tz = datetime.now().astimezone().tzinfo
        if isinstance(start, datetime):
            if start.tzinfo is not None:
                start = start.astimezone(local_tz)
            else:
                start = start.replace(tzinfo=local_tz)
            self._filter_from = start.date()
        else:
            self._filter_from = start
        if isinstance(end, datetime):
            if end.tzinfo is not None:
                end = end.astimezone(local_tz)
            else:
                end = end.replace(tzinfo=local_tz)
            self._filter_to = end.date()
        else:
            self._filter_to = end
        self._page.pop_dialog()
        await self._refresh_history()
        self._page.update()

    async def _on_search_change(self, _event) -> None:
        self._filter_search = (self._search_field.value or "").strip()
        await self._refresh_history()
        self._page.update()

    async def _clear_filters(self, _event) -> None:
        self._filter_from = None
        self._filter_to = None
        self._filter_search = ""
        self._search_field.value = ""
        await self._refresh_history()
        self._page.update()

    def _filters_active(self) -> bool:
        return bool(self._filter_from or self._filter_to or self._filter_search)

    def _apply_filters(self, checkpoints: list[Checkpoint]) -> list[Checkpoint]:
        result = checkpoints
        if self._filter_from is not None or self._filter_to is not None:
            start = self._filter_from or date.min
            end = self._filter_to or date.max
            result = [c for c in result if start <= datetime.fromisoformat(c.created_at).date() <= end]
        if self._filter_search:
            needle = self._filter_search.lower()
            result = [c for c in result if needle in c.note.lower()]
        return result

    def _describe_filters(self, count: int) -> str:
        if not self._filters_active():
            return f"Showing all {count} checkpoint(s)."
        parts = []
        if self._filter_from or self._filter_to:
            if self._filter_from and self._filter_to and self._filter_from == self._filter_to:
                parts.append(f"day = {self._filter_from.isoformat()}")
            else:
                start_text = self._filter_from.isoformat() if self._filter_from else "…"
                end_text = self._filter_to.isoformat() if self._filter_to else "…"
                parts.append(f"range = {start_text} to {end_text}")
        if self._filter_search:
            parts.append(f"note contains '{self._filter_search}'")
        return f"Showing {count} checkpoint(s), filtered by " + ", ".join(parts)

    async def _refresh_history(self, _event=None) -> None:
        fetch_task = asyncio.ensure_future(asyncio.to_thread(self._repository.all))
        delay_task = asyncio.ensure_future(asyncio.sleep(self.HISTORY_LOADING_DELAY_SECONDS))
        done, _pending = await asyncio.wait({fetch_task, delay_task}, return_when=asyncio.FIRST_COMPLETED)
        if fetch_task not in done:
            self._history_progress.visible = True
            self._history_loading_text.visible = True
            self._page.update()
        else:
            delay_task.cancel()
        all_checkpoints = await fetch_task
        checkpoints = self._apply_filters(all_checkpoints)
        self._displayed_checkpoints = checkpoints
        if not checkpoints:
            message = "No checkpoints match the current filter." if self._filters_active() else "No checkpoints recorded yet."
            self._history.controls = [ft.Text(message)]
        else:
            self._history.controls = [self._history_item(checkpoint) for checkpoint in checkpoints]
        self._filter_summary.value = self._describe_filters(len(checkpoints))
        self._history_progress.visible = False
        self._history_loading_text.visible = False
        self._page.update()

    def _history_item(self, checkpoint: Checkpoint) -> ft.Control:
        if checkpoint.source == "Manual":
            icon = ft.Icons.TOUCH_APP
        elif checkpoint.source == "Automatic stop":
            icon = ft.Icons.AUTO_MODE
        else:
            icon = ft.Icons.LOCATION_ON
        note = f" · {checkpoint.note}" if checkpoint.note else ""
        return ft.ListTile(
            leading=ft.Icon(icon),
            title=f"{checkpoint.source} · {checkpoint.coordinate_text}",
            subtitle=f"{checkpoint.created_at}{note}",
            trailing=ft.IconButton(
                icon=ft.Icons.OPEN_IN_NEW,
                icon_color=ft.Colors.GREEN,
                on_click=partial(self._open_map, checkpoint),
            ),
        )

    async def _open_map(self, checkpoint: Checkpoint) -> None:
        await self._url_launcher.launch_url(map_link(checkpoint), web_only_window_name="_blank")

    # --- Export --------------------------------------------------------------

    def _export_json(self, event) -> None:
        self._show_export_scope_dialog("json")

    def _export_markdown(self, event) -> None:
        self._show_export_scope_dialog("md")

    def _show_export_scope_dialog(self, kind: str) -> None:
        dialog = ft.AlertDialog(
            title=ft.Text("Export checkpoints"),
            content=ft.Text("Choose which checkpoints to export:"),
            actions=[
                ft.TextButton(content="Cancel", on_click=lambda _event: self._page.pop_dialog()),
                ft.TextButton(
                    content="All checkpoints",
                    on_click=partial(self._run_export, kind, True),
                ),
                ft.TextButton(
                    content="Filtered / shown",
                    on_click=partial(self._run_export, kind, False),
                ),
            ],
        )
        self._page.show_dialog(dialog)

    async def _set_export_busy(self, busy: bool, message: str = "") -> None:
        self._export_json_button.disabled = busy
        self._export_markdown_button.disabled = busy
        self._export_progress.visible = busy
        self._export_status.visible = busy
        self._export_status.value = message
        self._page.update()
        if busy:
            await asyncio.sleep(0)

    async def _run_export(self, kind: str, export_all: bool, _event) -> None:
        self._page.pop_dialog()
        checkpoints = await asyncio.to_thread(self._repository.all) if export_all else self._displayed_checkpoints
        if not checkpoints:
            self._export_status.value = "No checkpoints to export."
            self._page.update()
            return
        await self._set_export_busy(True, f"Preparing {len(checkpoints)} checkpoint(s)…")
        try:
            if kind == "json":
                content = await asyncio.to_thread(self._repository.to_json, checkpoints)
                await self._export("travel-checkpoints.json", content, "json")
            else:
                content = await asyncio.to_thread(self._repository.to_markdown, checkpoints)
                await self._export("travel-checkpoints.md", content, "md")
        finally:
            await self._set_export_busy(False)

    async def _export(self, file_name: str, content: str, extension: str) -> None:
        self._export_status.value = "Waiting for you to choose a save location…"
        self._page.update()
        await self._file_picker.save_file(
            dialog_title="Export travel checkpoints",
            file_name=file_name,
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=[extension],
            src_bytes=content.encode("utf-8"),
        )
        self._export_status.value = "Export ready to save."
        self._page.update()

    # --- Clear history ---------------------------------------------------

    def _confirm_clear_history(self, _event) -> None:
        self._clear_progress.visible = False
        self._clear_status.visible = False
        self._clear_status.value = ""
        for action in self._clear_dialog.actions:
            action.disabled = False
        self._page.show_dialog(self._clear_dialog)

    async def _set_clear_busy(self, busy: bool, message: str = "") -> None:
        self._clear_progress.visible = busy
        self._clear_status.visible = busy
        self._clear_status.value = message
        for action in self._clear_dialog.actions:
            action.disabled = busy
        self._page.update()
        if busy:
            await asyncio.sleep(0)

    async def _backup_and_clear(self, _event) -> None:
        checkpoints = await asyncio.to_thread(self._repository.all)
        if checkpoints:
            await self._set_clear_busy(True, f"Backing up {len(checkpoints)} checkpoint(s)…")
            await self._export_zip_backup(checkpoints)
        await self._set_clear_busy(True, "Clearing history…")
        await asyncio.to_thread(self._repository.delete_all)
        await self._clear_filters(_event)
        await self._set_clear_busy(False)
        self._page.pop_dialog()
        self._set_status("History exported and cleared.")
        self._page.update()

    async def _clear_without_backup(self, _event) -> None:
        await self._set_clear_busy(True, "Clearing history…")
        await asyncio.to_thread(self._repository.delete_all)
        await self._clear_filters(_event)
        await self._set_clear_busy(False)
        self._page.pop_dialog()
        self._set_status("History cleared.")
        self._page.update()

    async def _export_zip_backup(self, checkpoints: list[Checkpoint]) -> None:
        archive_bytes = await asyncio.to_thread(
            lambda: build_zip_backup(
                self._repository.to_json(checkpoints),
                self._repository.to_markdown(checkpoints),
            )
        )
        self._clear_status.value = "Waiting for you to choose a save location…"
        self._page.update()
        await self._file_picker.save_file(
            dialog_title="Export checkpoints backup",
            file_name="travel-checkpoints-backup.zip",
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["zip"],
            src_bytes=archive_bytes,
        )