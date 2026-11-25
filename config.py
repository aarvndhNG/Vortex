"""Settings, paths and download history for Vortex."""

from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
HISTORY_PATH = BASE_DIR / "history.json"

DEFAULTS: dict = {
    "download_dir": "downloads",
    "filename_template": "%(uploader,channel,creator|unknown)s - %(title)s [%(id)s].%(ext)s",
    "default_quality": "best",
    "concurrent_fragments": 4,
    "cookies_browser": "",
    "proxy": "",
    "rate_limit": "",
    "embed_metadata": True,
    "embed_thumbnail": True,
    "subtitles": False,
}

HISTORY_LIMIT = 500


def load() -> dict:
    """Read config.json, filling in anything missing with defaults."""
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
        except (OSError, json.JSONDecodeError):
            pass
    return cfg


def save(cfg: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except OSError:
        pass


def download_dir(cfg: dict) -> Path:
    """Resolve the download folder, relative paths living next to vd."""
    raw = str(cfg.get("download_dir") or "downloads").strip() or "downloads"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def load_history() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def add_history(entry: dict) -> None:
    entries = load_history()
    entries.append(entry)
    try:
        HISTORY_PATH.write_text(
            json.dumps(entries[-HISTORY_LIMIT:], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def clear_history() -> None:
    try:
        HISTORY_PATH.unlink()
    except OSError:
        pass
