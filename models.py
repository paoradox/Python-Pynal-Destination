from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Checkpoint:
    id: int | None
    latitude: float
    longitude: float
    created_at: str
    source: str
    note: str = ""

    @property
    def coordinate_text(self) -> str:
        return f"{self.latitude:.6f}, {self.longitude:.6f}"


class CheckpointRepository:
    def __init__(self, database_path: Path):
        self._database_path = database_path

    def initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection_scope() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

    def add(self, latitude: float, longitude: float, source: str, note: str = "") -> Checkpoint:
        created_at = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection_scope() as connection:
            cursor = connection.execute(
                "INSERT INTO checkpoints (latitude, longitude, created_at, source, note) VALUES (?, ?, ?, ?, ?)",
                (latitude, longitude, created_at, source, note.strip()),
            )
        return Checkpoint(cursor.lastrowid, latitude, longitude, created_at, source, note.strip())

    def all(self) -> list[Checkpoint]:
        with self._connection_scope() as connection:
            rows = connection.execute(
                "SELECT id, latitude, longitude, created_at, source, note "
                "FROM checkpoints ORDER BY created_at DESC"
            ).fetchall()
        return [Checkpoint(*row) for row in rows]

    def delete_all(self) -> None:
        with self._connection_scope() as connection:
            connection.execute("DELETE FROM checkpoints")

    def get_setting(self, key: str, default: str) -> str:
        with self._connection_scope() as connection:
            row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._connection_scope() as connection:
            connection.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def to_json(self, checkpoints: list[Checkpoint] | None = None) -> str:
        records = [
            {
                "timestamp": checkpoint.created_at,
                "latitude": checkpoint.latitude,
                "longitude": checkpoint.longitude,
                "source": checkpoint.source,
                "note": checkpoint.note,
                "map_link": map_link(checkpoint),
            }
            for checkpoint in (checkpoints if checkpoints is not None else self.all())
        ]
        return json.dumps(records, indent=2)

    def to_markdown(self, checkpoints: list[Checkpoint] | None = None) -> str:
        lines = [
            "# Travel checkpoints",
            "",
            "| Timestamp | Latitude | Longitude | Source | Note | Map link |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for checkpoint in checkpoints if checkpoints is not None else self.all():
            note = checkpoint.note.replace("|", "\\|") or "—"
            lines.append(
                f"| {checkpoint.created_at} | {checkpoint.latitude:.6f} | {checkpoint.longitude:.6f} "
                f"| {checkpoint.source} | {note} | [Open]({map_link(checkpoint)}) |"
            )
        return "\n".join(lines) + "\n"

    @contextlib.contextmanager
    def _connection_scope(self):
        connection = self._connection()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path)


def map_link(checkpoint: Checkpoint) -> str:
    return f"https://www.openstreetmap.org/?mlat={checkpoint.latitude}&mlon={checkpoint.longitude}#map=16/{checkpoint.latitude}/{checkpoint.longitude}"


def build_zip_backup(json_text: str, markdown_text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("travel-checkpoints.json", json_text)
        archive.writestr("travel-checkpoints.md", markdown_text)
    return buffer.getvalue()