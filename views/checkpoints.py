from __future__ import annotations

from datetime import date, datetime
from functools import partial

import flet as ft
import flet_geolocator as ftg

from models import Checkpoint, CheckpointRepository, build_zip_backup, map_link


class CheckpointView:
    STOP_SECONDS = 10 * 60
    STOP_SPEED_METERS_PER_SECOND = 1.0
    THEME_MODES = {
        "system": ft.ThemeMode.SYSTEM,
        "light": ft.ThemeMode.LIGHT,
        "dark": ft.ThemeMode.DARK,
    }

    def __init__(self, page: ft.Page, repository: CheckpointRepository):
        self._page = page
        self._repository = repository
        self._tracker_enabled = False
        self._still_since: datetime | None = None
        self._last_position: ftg.GeolocatorPosition | None = None
        self._last_auto_checkpoint_at: datetime | None = None

        # History filter state
        self._filter_day: date | None = None
        self._filter_from: date | None = None
        self._filter_to: date | None = None
        self._filter_search: str = ""
        self._displayed_checkpoints: list[Checkpoint] = []

        self._geolocator = ftg.Geolocator(
            configuration=ftg.GeolocatorConfiguration(
                accuracy=ftg.GeolocatorPositionAccuracy.HIGH,
                distance_filter=25,
            ),
            on_position_change=self._on_position_change,
            on_error=self._on_location_error,
        )
        self._file_picker = ft.FilePicker()
        self._day_picker = ft.DatePicker(help_text="Filter by day", on_change=self._on_day_picked)
        self._from_picker = ft.DatePicker(help_text="From date", on_change=self._on_from_picked)
        self._to_picker = ft.DatePicker(help_text="To date", on_change=self._on_to_picked)
        self._page.services.extend([self._geolocator, self._file_picker])

        self._tracking_switch = ft.Switch(label="Automatic stop detection", on_change=self._toggle_tracking)
        self._status = ft.Text("Automatic detection is paused.")
        self._note = ft.TextField(label="Optional note for the next checkpoint")
        self._search_field = ft.TextField(label="Search notes", on_change=self._on_search_change, expand=True)
        self._filter_summary = ft.Text("Showing all checkpoints.")
        self._history = ft.ListView(expand=True)
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

    async def initialize(self) -> None:
        self._repository.initialize()
        saved_mode = self._repository.get_setting("theme_mode", "system")
        selected_mode = saved_mode if saved_mode in self.THEME_MODES else "system"
        self._theme_selector.value = selected_mode
        self._page.theme_mode = self.THEME_MODES[selected_mode]
        self._refresh_history()

    def control(self) -> ft.Control:
        return ft.SafeArea(content=self._tabs, expand=True)

    def _record_panel(self) -> ft.Control:
        return ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
            controls=[
                ft.Text(
                    "Save a stop now, or allow the app to save a checkpoint\nafter ten minutes of stillness.",
                    text_align=ft.TextAlign.CENTER,
                ),
                self._tracking_switch,
                self._status,
                self._note,
                ft.Button(content="Record current stop", icon=ft.Icons.LOCATION_ON, on_click=self._record_manual),
                ft.Text(
                    "Location history stays on this device. Background tracking depends on\n"
                    "the location permission you grant and your phone's battery settings.",
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
        )

    def _history_panel(self) -> ft.Control:
        return ft.Column(
            expand=True,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.CENTER,
                    controls=[
                        ft.Button(content="Export JSON (.json)", icon=ft.Icons.FILE_DOWNLOAD, on_click=self._export_json),
                        ft.Button(content="Export Markdown (.md)", icon=ft.Icons.DESCRIPTION, on_click=self._export_markdown),
                    ],
                    wrap=True,
                ),
                ft.Row(
                    alignment=ft.MainAxisAlignment.CENTER,
                    controls=[
                        ft.Text(
                            "Tap the icon on a checkpoint to open it in OpenStreetMap.",
                            text_align=ft.TextAlign.CENTER,
                        )
                    ],
                ),
                ft.Text("Filters", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                ft.Row(
                    alignment=ft.MainAxisAlignment.CENTER,
                    wrap=True,
                    controls=[
                        ft.Button(
                            content="Filter by day",
                            icon=ft.Icons.CALENDAR_MONTH,
                            on_click=lambda _event: self._page.show_dialog(self._day_picker),
                        ),
                        ft.Button(
                            content="From",
                            icon=ft.Icons.CALENDAR_MONTH,
                            on_click=lambda _event: self._page.show_dialog(self._from_picker),
                        ),
                        ft.Button(
                            content="To",
                            icon=ft.Icons.CALENDAR_MONTH,
                            on_click=lambda _event: self._page.show_dialog(self._to_picker),
                        ),
                        ft.TextButton(content="Clear filters", icon=ft.Icons.CLEAR, on_click=self._clear_filters),
                    ],
                ),
                self._search_field,
                self._filter_summary,
                self._history,
            ],
        )

    def _settings_panel(self) -> ft.Control:
        return ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
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
                ft.Text("Danger zone", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                ft.Text(
                    "Permanently delete every checkpoint saved on this device.",
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Button(
                    content="Clear history",
                    icon=ft.Icons.DELETE_FOREVER,
                    on_click=self._confirm_clear_history,
                ),
            ],
        )

    def _change_theme(self, _event) -> None:
        selected_mode = self._theme_selector.value or "system"
        self._page.theme_mode = self.THEME_MODES[selected_mode]
        self._repository.set_setting("theme_mode", selected_mode)
        self._page.update()

    async def _toggle_tracking(self, _event) -> None:
        if self._tracking_switch.value:
            permission = await self._geolocator.request_permission()
            if permission not in (
                ftg.GeolocatorPermissionStatus.ALWAYS,
                ftg.GeolocatorPermissionStatus.WHILE_IN_USE,
            ):
                self._tracking_switch.value = False
                self._status.value = "Location permission is needed to detect stops."
            else:
                self._tracker_enabled = True
                self._status.value = "Detecting long pauses while location updates are available."
        else:
            self._tracker_enabled = False
            self._still_since = None
            self._status.value = "Automatic detection is paused."
        self._page.update()

    async def _record_manual(self, _event) -> None:
        position = await self._geolocator.get_current_position()
        await self._save_position(position, "Manual")

    async def _on_position_change(self, event: ftg.GeolocatorPositionChangeEvent) -> None:
        self._last_position = event.position
        if not self._tracker_enabled:
            return
        speed = event.position.speed or 0.0
        now = datetime.now().astimezone()
        if speed <= self.STOP_SPEED_METERS_PER_SECOND:
            self._still_since = self._still_since or now
            if (now - self._still_since).total_seconds() >= self.STOP_SECONDS and self._can_record_auto(now):
                await self._save_position(event.position, "Automatic stop")
                self._last_auto_checkpoint_at = now
        else:
            self._still_since = None
            self._status.value = "Movement detected; watching for the next long pause."
            self._page.update()

    async def _save_position(self, position: ftg.GeolocatorPosition, source: str) -> None:
        if position.latitude is None or position.longitude is None:
            self._status.value = "The device did not provide a usable coordinate."
            self._page.update()
            return
        checkpoint = self._repository.add(
            float(position.latitude),
            float(position.longitude),
            source,
            self._note.value,
        )
        self._note.value = ""
        self._status.value = f"{source} checkpoint saved at {checkpoint.coordinate_text}."
        self._refresh_history()
        self._page.update()

    def _can_record_auto(self, now: datetime) -> bool:
        return self._last_auto_checkpoint_at is None or (now - self._last_auto_checkpoint_at).total_seconds() >= self.STOP_SECONDS

    def _on_location_error(self, _event) -> None:
        self._status.value = "Location updates are unavailable. Check Location Services and permissions."
        self._page.update()

    # --- History filtering -------------------------------------------------

    def _on_day_picked(self, _event) -> None:
        if self._day_picker.value:
            picked = self._day_picker.value
            self._filter_day = picked.date() if isinstance(picked, datetime) else picked
            self._filter_from = None
            self._filter_to = None
        self._page.pop_dialog()
        self._refresh_history()
        self._page.update()

    def _on_from_picked(self, _event) -> None:
        if self._from_picker.value:
            picked = self._from_picker.value
            self._filter_from = picked.date() if isinstance(picked, datetime) else picked
            self._filter_day = None
        self._page.pop_dialog()
        self._refresh_history()
        self._page.update()

    def _on_to_picked(self, _event) -> None:
        if self._to_picker.value:
            picked = self._to_picker.value
            self._filter_to = picked.date() if isinstance(picked, datetime) else picked
            self._filter_day = None
        self._page.pop_dialog()
        self._refresh_history()
        self._page.update()

    def _on_search_change(self, _event) -> None:
        self._filter_search = (self._search_field.value or "").strip()
        self._refresh_history()
        self._page.update()

    def _clear_filters(self, _event) -> None:
        self._filter_day = None
        self._filter_from = None
        self._filter_to = None
        self._filter_search = ""
        self._search_field.value = ""
        self._refresh_history()
        self._page.update()

    def _filters_active(self) -> bool:
        return bool(self._filter_day or self._filter_from or self._filter_to or self._filter_search)

    def _apply_filters(self, checkpoints: list[Checkpoint]) -> list[Checkpoint]:
        result = checkpoints
        if self._filter_day is not None:
            result = [c for c in result if datetime.fromisoformat(c.created_at).date() == self._filter_day]
        elif self._filter_from is not None or self._filter_to is not None:
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
        if self._filter_day:
            parts.append(f"day = {self._filter_day.isoformat()}")
        if self._filter_from or self._filter_to:
            start_text = self._filter_from.isoformat() if self._filter_from else "…"
            end_text = self._filter_to.isoformat() if self._filter_to else "…"
            parts.append(f"range = {start_text} to {end_text}")
        if self._filter_search:
            parts.append(f"note contains '{self._filter_search}'")
        return f"Showing {count} checkpoint(s), filtered by " + ", ".join(parts)

    def _refresh_history(self) -> None:
        checkpoints = self._apply_filters(self._repository.all())
        self._displayed_checkpoints = checkpoints
        if not checkpoints:
            message = "No checkpoints match the current filter." if self._filters_active() else "No checkpoints recorded yet."
            self._history.controls = [ft.Text(message)]
        else:
            self._history.controls = [self._history_item(checkpoint) for checkpoint in checkpoints]
        self._filter_summary.value = self._describe_filters(len(checkpoints))

    def _history_item(self, checkpoint: Checkpoint) -> ft.Control:
        note = f" · {checkpoint.note}" if checkpoint.note else ""
        return ft.ListTile(
            leading=ft.Icons.LOCATION_ON,
            title=f"{checkpoint.source} · {checkpoint.coordinate_text}",
            subtitle=f"{checkpoint.created_at}{note}",
            trailing=ft.IconButton(icon=ft.Icons.OPEN_IN_NEW, on_click=partial(self._open_map, checkpoint)),
        )

    async def _open_map(self, checkpoint: Checkpoint) -> None:
        await self._page.launch_url(map_link(checkpoint), web_popup_window_name=ft.UrlTarget.BLANK)

    # --- Export --------------------------------------------------------------

    def _export_json(self, event) -> None:
        if self._filters_active():
            self._show_export_scope_dialog("json")
        else:
            self._page.run_task(self._run_export, "json", True, event)

    def _export_markdown(self, event) -> None:
        if self._filters_active():
            self._show_export_scope_dialog("md")
        else:
            self._page.run_task(self._run_export, "md", True, event)

    def _show_export_scope_dialog(self, kind: str) -> None:
        dialog = ft.AlertDialog(
            title=ft.Text("Export checkpoints"),
            content=ft.Text("Export all checkpoints, or only what's currently shown by your filter/search?"),
            actions=[
                ft.TextButton(content="All checkpoints", on_click=partial(self._run_export, kind, True)),
                ft.TextButton(content="Filtered / shown", on_click=partial(self._run_export, kind, False)),
            ],
        )
        self._page.show_dialog(dialog)

    async def _run_export(self, kind: str, export_all: bool, _event) -> None:
        self._page.pop_dialog()
        checkpoints = self._repository.all() if export_all else self._displayed_checkpoints
        if not checkpoints:
            self._status.value = "No checkpoints to export."
            self._page.update()
            return
        if kind == "json":
            await self._export("travel-checkpoints.json", self._repository.to_json(checkpoints), "json")
        else:
            await self._export("travel-checkpoints.md", self._repository.to_markdown(checkpoints), "md")

    async def _export(self, file_name: str, content: str, extension: str) -> None:
        await self._file_picker.save_file(
            dialog_title="Export travel checkpoints",
            file_name=file_name,
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=[extension],
            src_bytes=content.encode("utf-8"),
        )
        self._status.value = "Export ready to save."
        self._page.update()

    # --- Clear history ---------------------------------------------------

    def _confirm_clear_history(self, _event) -> None:
        dialog = ft.AlertDialog(
            title=ft.Text("Clear all history?"),
            content=ft.Text(
                "This permanently deletes every checkpoint saved on this device. This cannot be undone."
            ),
            actions=[
                ft.TextButton(content="Cancel", on_click=lambda _event: self._page.pop_dialog()),
                ft.TextButton(content="Export backup, then clear", on_click=self._backup_and_clear),
                ft.TextButton(content="Clear without backup", on_click=self._clear_without_backup),
            ],
        )
        self._page.show_dialog(dialog)

    async def _backup_and_clear(self, _event) -> None:
        self._page.pop_dialog()
        checkpoints = self._repository.all()
        if checkpoints:
            await self._export_zip_backup(checkpoints)
        self._repository.delete_all()
        self._clear_filters(_event)
        self._status.value = "History exported and cleared."
        self._page.update()

    async def _clear_without_backup(self, _event) -> None:
        self._page.pop_dialog()
        self._repository.delete_all()
        self._clear_filters(_event)
        self._status.value = "History cleared."
        self._page.update()

    async def _export_zip_backup(self, checkpoints: list[Checkpoint]) -> None:
        archive_bytes = build_zip_backup(
            self._repository.to_json(checkpoints),
            self._repository.to_markdown(checkpoints),
        )
        await self._file_picker.save_file(
            dialog_title="Export checkpoints backup",
            file_name="travel-checkpoints-backup.zip",
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["zip"],
            src_bytes=archive_bytes,
        )