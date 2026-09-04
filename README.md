# Pynal Destination — Location History Recorder

**Pynal Destination** is a cross-platform app that records and retraces stops from long drives and commutes with private, on-device location history. Built with [Flet](https://flet.dev/) and a local SQLite database.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| **Automatic Checkpoint Detection** | Captures a location automatically when you stop for a configurable duration, using background geolocation |
| **Manual Checkpoint Recording** | Capture your current location on demand |
| **History View** | Browse recorded checkpoints with coordinates, timestamps, source (Manual/Automatic), and optional notes |
| **Search & Filter** | Search and date‑range filtering of the checkpoint history |
| **Open in Map** | Jump straight to a checkpoint's location on OpenStreetMap |
| **Export** | Export checkpoints as JSON or Markdown — full history or currently filtered set |
| **Backup & Clear** | Back up all checkpoints to a `.zip` (JSON + Markdown) before clearing history, or clear without a backup |
| **Settings** | Appearance (theme) and configurable auto‑detection stop duration |
| **Cross‑Platform** | Supports desktop and mobile (Android/iOS), using platform‑appropriate storage for the database |

---

## 🛠️ Tech Stack

| Category | Technologies |
|----------|--------------|
| **Programming Language** | Python (>= 3.12) |
| **UI Framework** | [Flet](https://flet.dev/) |
| **Geolocation** | flet‑geolocator |
| **Database** | SQLite (via Python's built‑in `sqlite3`) |
| **Dev Tools** | flet‑cli, flet‑desktop, flet‑web |

---

## 📁 Project Structure

```
Python-Pynal-Destination/
├── main.py                 # App entry point
├── models.py               # Checkpoint data model + SQLite repository (CRUD, export helpers)
├── views/
│   └── checkpoints.py      # Main UI: recording, history, filters, export, settings
├── assets/
│   ├── icon.png
│   └── icon.svg
├── pyproject.toml          # Project metadata, dependencies, Flet/Android config
└── requirements.txt
```

> **Note:** The `views/` folder currently contains duplicate copies of `main.py`, `models.py`, `pyproject.toml`, and `requirements.txt` (identical to the root versions), plus a further nested `views/views/` copy of the views package. These look like leftovers from a refactor — you may want to clean these up, since the app's actual imports (`from views.checkpoints import CheckpointView`) only need `views/checkpoints.py`.

---

## 🚀 Getting Started

### Prerequisites

- Python 3.12 or later
- pip

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/paoradox/Python-Pynal-Destination.git
   cd Python-Pynal-Destination
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

### Usage

Run the app with:
```bash
flet run main.py
```
Or using the standard Python entry point:
```bash
python main.py
```

On desktop/web, the database is stored as `travel_checkpoints.db` in the working directory; on Android/iOS, it's stored in the app's documents directory.

### Configuration

- **Android permissions:** `pyproject.toml` declares the Android permissions needed for background location tracking (`ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION`, `ACCESS_BACKGROUND_LOCATION`, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_LOCATION`, `WAKE_LOCK`).
- **Auto‑detection stop duration** and **theme** can be changed from the in‑app Settings panel; these are persisted in the local database's `settings` table.

---

## 🖼️ Preview

_Add a screenshot of the app here_

> **Tip:** You can add a screenshot by uploading an image to the repository and linking it here.

---

## 🎮 How to Use

1. Launch the app and grant location permissions when prompted.
2. **Automatic mode:** The app captures a checkpoint whenever you stop moving for the configured duration.
3. **Manual mode:** Tap the record button to save your current location instantly.
4. Browse your history, search, filter by date, and export your checkpoints.
5. Use the Settings panel to adjust the stop duration or switch themes.

---

## 👥 Contributors

| Name | Role |
|------|------|
| **J.P. Ancheta Javier** | Developer |

---

## 📄 License & Disclaimer

This project is for **educational purposes** and is not intended for commercial distribution.

> **NO WARRANTY** — This software is provided "as is" without any warranties of any kind.

- **No commercial use** — This project was not intended for commercial distribution.
- **Privacy** — All data stays on‑device in a local SQLite database; nothing is sent to a remote server.

---

## 🙏 Acknowledgements

- Built with [**Flet**](https://flet.dev/) and **Python**
- Location services powered by **flet‑geolocator**
- Maps integration via **OpenStreetMap**

---

**Pynal Destination** — Record and retrace your journey · 2026
