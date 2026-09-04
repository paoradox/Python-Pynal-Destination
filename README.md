# Pynal Destination — Location History

Record and retrace stops from long drives and commutes with private, on-device location history. Built with [Flet](https://flet.dev/) and a local SQLite database.

## Description

Pynal Destination automatically (or manually) records "checkpoints" — timestamped GPS coordinates — while you're on the move, so you can retrace stops from a trip later. All data stays on-device in a local SQLite database; nothing is sent to a remote server.

## Features

- **Automatic checkpoint detection** — captures a location automatically when you stop for a configurable duration, using background geolocation (Android permissions for background/foreground location tracking are configured in the project)
- **Manual checkpoint recording** — capture your current location on demand
- **History view** — browse recorded checkpoints, each with a coordinate, timestamp, source (Manual/Automatic), and optional note
- **Search & date-range filtering** of the checkpoint history
- **Open in map** — jump straight to a checkpoint's location on OpenStreetMap
- **Export** — export checkpoints as JSON or Markdown, either the full history or the currently filtered set
- **Backup & clear** — back up all checkpoints to a `.zip` (JSON + Markdown) before clearing history, or clear without a backup
- **Settings** — appearance (theme) and configurable auto-detection stop duration
- **Cross-platform** — supports desktop and mobile (Android/iOS), using the platform-appropriate storage location for the database

## Tech Stack

- **Python** (>= 3.12)
- [**Flet**](https://flet.dev/) — UI framework
- **flet-geolocator** — geolocation/location permissions
- **SQLite** (via Python's built-in `sqlite3`) — local checkpoint storage
- Dev tools: `flet-cli`, `flet-desktop`, `flet-web`

## Prerequisites

- Python 3.12 or later
- pip

## Installation

Clone the repository:

```bash
git clone https://github.com/paoradox/Python-Pynal-Destination.git
cd Python-Pynal-Destination
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Usage

Run the app:

```bash
flet run main.py
```

Or, using the standard Python entry point:

```bash
python main.py
```

On desktop/web, the database is stored as `travel_checkpoints.db` in the working directory; on Android/iOS, it's stored in the app's documents directory.

## Configuration

- **Android permissions:** `pyproject.toml` declares the Android permissions needed for background location tracking (`ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION`, `ACCESS_BACKGROUND_LOCATION`, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_LOCATION`, `WAKE_LOCK`).
- **Auto-detection stop duration** and **theme** can be changed from the in-app Settings panel; these are persisted in the local database's `settings` table.

## Project Structure

```
Python-Pynal-Destination/
├── main.py               # App entry point
├── models.py              # Checkpoint data model + SQLite repository (CRUD, export helpers)
├── views/
│   ├── checkpoints.py     # Main UI: recording, history, filters, export, settings
│   ├── old/               # Archived earlier drafts of checkpoints.py (not used by the app)
│   ├── main.py            # Duplicate of the root main.py
│   ├── models.py          # Duplicate of the root models.py
│   ├── views/              # Duplicate nested copy of the views package (checkpoints.py, old/)
│   ├── pyproject.toml      # Duplicate of the root pyproject.toml
│   └── requirements.txt    # Duplicate of the root requirements.txt
├── assets/
│   ├── icon.png
│   └── icon.svg
├── pyproject.toml         # Project metadata, dependencies, Flet/Android config
└── requirements.txt
```

> **Note:** the `views/` folder currently contains duplicate copies of `main.py`, `models.py`, `pyproject.toml`, and `requirements.txt` (identical to the root versions), plus a further nested `views/views/` copy of the views package. These look like leftovers from a refactor rather than intentional structure — you may want to clean these up, since the app's actual imports (`from views.checkpoints import CheckpointView`) only need `views/checkpoints.py`.

## Author

J.P Ancheta Javier

## License

Not specified.
