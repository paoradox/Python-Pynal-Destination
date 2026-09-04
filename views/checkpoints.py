from __future__ import annotations

import asyncio
from datetime import date, datetime
from functools import partial

import flet as ft
import flet_geolocator as ftg

from models import Checkpoint, CheckpointRepository, build_zip_backup, map_link


class CheckpointView:
    # Research on GPS stop-detection (Zhao et al. 2015; Cich et al. 2016; Hwang et al.;
    # Traccar's real-world default) converges on roughly 3-10 minutes of near-zero speed
    # to distinguish a genuine stop from a traffic light or a walking pause, with the
    # optimal value depending a lot on the individual's travel patterns. 5 minutes is a
    # reasonable middle default; it's exposed as a Settings option since "optimal" varies
    # per person/route.
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

        # History filter state
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
        self._url_launcher = ft.UrlLauncher()
        self._date_range_picker = ft.DateRangePicker(
            help_text="Filter by date(s) — pick one day, or a start and end",
            on_change=self._on_date_range_picked,
        )
        self._page.services.extend([self._geolocator, self._file_picker, self._url_launcher])

        self._tracking_switch = ft.Switch(label="Automatic stop detection", on_change=self._toggle_tracking)
        self._status = ft.Text("Automatic detection is paused.")

        self._search_field = ft.TextField(
            label="Search notes",
            dense=True,
            on_change=self._on_search_change,
            width=220,
        )
        self._filter_summary = ft.Text("Showing all checkpoints.")
        self._history_progress = ft.ProgressBar(width=280, visible=False)
        self._history_loading_text = ft.Text("Loading checkpoints…", visible=False)
        self._history = ft.ListView(expand=True)

        self._export_json_button = ft.Button(content="Export JSON (.json)", icon=ft.Icons.FILE_DOWNLOAD, on_click=self._export_json)
        self._export_markdown_button = ft.Button(content="Export Markdown (.md)", icon=ft.Icons.DESCRIPTION, on_click=self._export_markdown)
        self._export_progress = ft.ProgressBar(width=280, visible=False)
        self._export_status = ft.Text("", visible=False)

        self._clear_progress = ft.ProgressBar(width=280, visible=False)
        self._clear_status = ft.Text("", visible=False)
        self._clear_dialog = ft.AlertDialog(
            title=ft.Text("Clear all history?"),
            content=ft.Column(
                tight=True,
                controls=[
                    ft.Text(
                        "This permanently deletes every checkpoint saved on this device. This cannot be undone."
                    ),
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

        await self._refresh_history()

    def control(self) -> ft.Control:
        return ft.SafeArea(content=self._tabs, expand=True)

    def _record_panel(self) -> ft.Control:
        self._stop_duration_display = ft.Text(
            f"Stop detection duration: {self._stop_seconds // 60} minutes (adjust in Settings)"
        )
        return ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Text(
                    "Save a stop now, or allow the app to save a checkpoint\nafter you've been still for a while.",
                    text_align=ft.TextAlign.CENTER,
                ),
                self._tracking_switch,
                self._status,
                self._stop_duration_display,
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
                    controls=[self._export_json_button, self._export_markdown_button],
                    wrap=True,
                ),
                ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[self._export_progress]),
                ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[self._export_status]),
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
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    wrap=True,
                    controls=[
                        self._search_field,
                        ft.Button(
                            content="Pick date(s)",
                            icon=ft.Icons.DATE_RANGE,
                            on_click=lambda _event: self._page.show_dialog(self._date_range_picker),
                        ),
                        ft.TextButton(content="Clear filters", icon=ft.Icons.CLEAR, on_click=self._clear_filters),
                    ],
                ),
                self._filter_summary,
                ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[self._history_progress]),
                ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[self._history_loading_text]),
                self._history,
            ],
        )

    def _settings_panel(self) -> ft.Control:
        return ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
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
                    "How long you must stay still before a checkpoint saves automatically.\n"
                    "Shorter catches quick stops but may trigger at traffic lights;\n"
                    "longer only catches longer stops.",
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Row(
                    alignment=ft.MainAxisAlignment.CENTER,
                    controls=[self._stop_duration_selector],
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

    def _change_stop_duration(self, _event) -> None:
        selected = self._stop_duration_selector.value or self.DEFAULT_STOP_DURATION
        self._stop_seconds = self.STOP_DURATION_OPTIONS.get(
            selected, self.STOP_DURATION_OPTIONS[self.DEFAULT_STOP_DURATION]
        )
        self._repository.set_setting("stop_duration_minutes", selected)
        self._update_stop_duration_display()
        self._page.update()

    def _update_stop_duration_display(self) -> None:
        if hasattr(self, "_stop_duration_display"):
            self._stop_duration_display.value = (
                f"Stop detection duration: {self._stop_seconds // 60} minutes (adjust in Settings)"
            )

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
            if (now - self._still_since).total_seconds() >= self._stop_seconds and self._can_record_auto(now):
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
        await self._refresh_history()
        self._page.update()

    def _can_record_auto(self, now: datetime) -> bool:
        return self._last_auto_checkpoint_at is None or (now - self._last_auto_checkpoint_at).total_seconds() >= self._stop_seconds

    def _on_location_error(self, _event) -> None:
        self._status.value = "Location updates are unavailable. Check Location Services and permissions."
        self._page.update()

    # --- History filtering -------------------------------------------------

    async def _on_date_range_picked(self, _event) -> None:
        start = self._date_range_picker.start_value
        end = self._date_range_picker.end_value
        self._filter_from = start.date() if isinstance(start, datetime) else start
        self._filter_to = end.date() if isinstance(end, datetime) else end
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

    async def _refresh_history(self) -> None:
        fetch_task = asyncio.ensure_future(asyncio.to_thread(self._repository.all))
        delay_task = asyncio.ensure_future(asyncio.sleep(self.HISTORY_LOADING_DELAY_SECONDS))
        done, _pending = await asyncio.wait({fetch_task, delay_task}, return_when=asyncio.FIRST_COMPLETED)
        if fetch_task not in done:
            # Fetch is taking a while (a large history) — only now show the indicator,
            # so quick loads never flash it.
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
        note = f" · {checkpoint.note}" if checkpoint.note else ""
        return ft.ListTile(
            leading=ft.Icons.LOCATION_ON,
            title=f"{checkpoint.source} · {checkpoint.coordinate_text}",
            subtitle=f"{checkpoint.created_at}{note}",
            trailing=ft.IconButton(icon=ft.Icons.OPEN_IN_NEW, on_click=partial(self._open_map, checkpoint)),
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
            # Yield to the event loop so the progress bar actually paints before the
            # (possibly slow, for large histories) work below runs.
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
        self._status.value = "History exported and cleared."
        self._page.update()

    async def _clear_without_backup(self, _event) -> None:
        await self._set_clear_busy(True, "Clearing history…")
        await asyncio.to_thread(self._repository.delete_all)
        await self._clear_filters(_event)
        await self._set_clear_busy(False)
        self._page.pop_dialog()
        self._status.value = "History cleared."
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