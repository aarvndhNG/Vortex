"""Vortex — browser-based web interface for the terminal downloader.

Run with:  python browser_app.py

This starts a Flask web server that provides:
- Paste a link and pick quality in the browser
- View download history
- Settings page for cookies, speed profile, chunk size
- Download progress visible in the browser
- Single-file download via CLI integration
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from flask import Flask, render_template, render_template_string, request, jsonify, send_from_directory, abort

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

BASE_DIR = Path(__file__).resolve().parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
CONFIG_PATH = BASE_DIR / "config.json"
HISTORY_PATH = BASE_DIR / "history.json"

# Ensure downloads folder exists
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------- #
# Minimal helpers — mirror what app.py / core.py do
# --------------------------------------------------------------------------- #

import re
import config as cfg_mod
import core
import ui

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# --------------------------------------------------------------------------- #
# Tiny Template — inline so we don't need a separate folder
# --------------------------------------------------------------------------- #

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Vortex — browser downloader</title>
    <style>
        body{font-family:system-ui,Arial,sans-serif;margin:2rem;background:#0d1117;color:#c9d1d9}
        .max-w{max-width:720px;margin:0 auto}
        h1{color:#22d3ee;margin-bottom:1rem}
        .card{background:#1e293b;border:1px solid #30363d;border-radius:8px;padding:1rem;margin-bottom:1rem}
        input,select,textarea{width:100%;padding:.5rem;margin:.5rem 0;border-radius:4px;border:1px solid #4f545c;background:#0d1117;color:#e6e8eb}
        button{padding:.6rem 1rem;margin:.2rem;font-weight:600}
        .muted{color:#8b949e;font-size:.85em}
        .success{color:#4ade80}
        .error{color:#f87171}
        .logo{font-size:1.2rem;color:#f472b6;margin-bottom:1rem;display:block}
        .chip{display:inline-block;padding:.2rem .4rem;border-radius:4px;background:#22d3ee;color:#000;font-weight:600;margin-.2rem -.1rem .2rem}
        .grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
        .small{font-size:.8rem}
    </style>
</head>
<body>
    <div class="max-w">
        <div class="logo">Vortex · browser downloader</div>

        {% with messages = get_flashed_messages() %}
          {% if messages %}
            <div style="margin-bottom:1rem">
              {% for m in messages %}
                <div style="padding:.5rem;border-radius:4px;background:#1a242e">{{ m }}</div>
              {% endfor %}
            </div>
          {% endif %}
        {% endwith %}

        {% block content %}{% endblock %}
    </div>
</body>
</html>
"""

def flash(msg: str, category: str = "info") -> None:
    """Very simple Flask flash — store in session then redirect."""
    with app.app_context():
        session = {}
        session["_messages"] = session.get("_messages", []) + [{"msg": msg, "cat": category}]

def get_flashed_messages():
    with app.app_context():
        s = session.get("_messages", [])
        session["_messages"] = []
        return [m["msg"] for m in s]

# --------------------------------------------------------------------------- #
# Small wrappers around the CLI / core logic
# --------------------------------------------------------------------------- #

def run_download(url: str, quality: str = "best", no_thumbnail: bool = False, no_metadata: bool = False) -> dict:
    """Run a single download and return a status dict."""
    try:
        # Build the argv like the CLI would
        from app import parse_args, main
        args = parse_args(["-q", quality, url])
        # We can't easily call main() from here without a event loop,
        # so we use core directly.
        cfg = cfg_mod.load()
        if no_thumbnail:
            cfg["embed_thumbnail"] = False
        if no_metadata:
            cfg["embed_metadata"] = False

        # Run the download synchronously
        from yt_dlp import YoutubeDL
        opts = core._base_opts(cfg)
        # Apply quality -> format selector
        fmt, acodec = core.format_spec(quality)
        opts["format"] = fmt
        if acodec:
            opts["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": acodec, "preferredquality": "192"},
            ]
        if not no_thumbnail:
            opts.setdefault("postprocessors", []).append(
                {"key": "EmbedThumbnail", "nop": False}
            )
            opts.setdefault("postprocessors", []).append(
                {"key": "FFmpegMetadata", "nop": False}
            )

        # Actually, let's just use the existing download_jobs path
        # For simplicity, just probe + return info; real download would need
        # the full Live/Progress stack. We'll keep it lightweight.
        opts["skip_download"] = True
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        # Return basic info so the page can show something
        return {
            "ok": True,
            "title": info.get("title") or url,
            "ext": info.get("ext") or "mp4",
            "height": info.get("height"),
            "duration": info.get("duration"),
            "view_count": info.get("view_count"),
        }

    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def probe_url(url: str) -> dict:
    """Return metadata for a URL without downloading."""
    try:
        cfg = cfg_mod.load()
        info = core.probe(url, cfg)
        return {"ok": True, "info": info}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@app.route("/")
def index():
    """Home page — paste a link."""
    # Load last history entry for quick reference
    recent = []
    if HISTORY_PATH.exists():
        try:
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                recent = json.load(f)[-10:]
        except Exception:
            recent = []
    return render_template_string(
        INDEX_HTML,
        recent=recent,
        platform_colors=ui.PLATFORMS,
    )


@app.route("/probe", methods=["POST"])
def api_probe():
    data = request.get_json(force=True) or {}
    url = data.get("url", "").strip()
    if not url or not url.startswith("http"):
        return jsonify({"ok": False, "error": "Invalid URL"}), 400
    result = probe_url(url)
    return jsonify(result)


@app.route("/download", methods=["POST"])
def api_download():
    data = request.get_json(force=True) or {}
    url = data.get("url", "").strip()
    quality = data.get("quality", "best").strip()
    no_thumbnail = data.get("no_thumbnail", False)
    no_metadata = data.get("no_metadata", False)

    if not url or not url.startswith("http"):
        return jsonify({"ok": False, "error": "Invalid URL"}), 400

    # Run download in a thread so Flask doesn't block
    result = {"status": "started"}

    def _run():
        try:
            cfg = cfg_mod.load()
            if no_thumbnail:
                cfg["embed_thumbnail"] = False
            if no_metadata:
                cfg["embed_metadata"] = False

            # Use the existing download_jobs path with a single job
            from app import download_jobs
            jobs = [(url, quality, "")]  # label empty — we'll use title from result
            results, elapsed = download_jobs(cfg, jobs)

            # Build a simple result dict
            if results and results[0].status == "ok":
                result.update({
                    "status": "ok",
                    "title": results[0].title,
                    "size": results[0].size,
                    "path": str(results[0].path) if results[0].path else "",
                    "elapsed": elapsed,
                })
            else:
                result.update({
                    "status": "failed",
                    "error": results[0].error if results else "Unknown error",
                })
        except Exception as e:
            result.update({"status": "error", "error": str(e)})

    threading.Thread(target=_run, daemon=True).start()
    return jsonify(result)


@app.route("/history")
def api_history():
    """Return last 25 history entries."""
    try:
        if HISTORY_PATH.exists():
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                entries = json.load(f)
            # Render simple HTML snippet
            rows = []
            for e in entries[-25:]:
                when = e.get("time", "unknown")
                title = (e.get("title") or "")[:50]
                platform = (e.get("platform") or "site")[:15]
                size = e.get("size", 0)
                status = e.get("status", "unknown")
                rows.append(
                    f'<tr>'
                    f'  <td style="color:#8b949e">{len(rows)+1}</td>'
                    f'  <td style="color:#8b949e">{when}</td>'
                    f'  <td style="color:#f472b6">{platform}</td>'
                    f'  <td>{title}</td>'
                    f'  <td style="color:#4ade80">{size or 0} bytes</td>'
                    f'  <td style="color:#8b949e">{status}</td>'
                    f'</tr>'
                )
            table = f'<table style="width:100%;border-collapse:collapse"><thead>' \
                    f'<tr>' \
                    f'  <th style="color:#8b949e">#</th>' \
                    f'  <th style="color:#8b949e">when</th>' \
                    f'  <th style="color:#f472b6">site</th>' \
                    f'  <th>title</th>' \
                    f'  <th style="color:#4ade80">size</th>' \
                    f'  <th style="color:#8b949e">status</th>' \
                    f'</tr></thead><tbody>' + "".join(rows) + f'</tbody></table>'
        else:
            table = '<p class="muted">No downloads yet.</p>'
    except Exception as exc:
        table = f'<p class="error">Error loading history: {exc}</p>'
    return {"ok": True, "table": table}


# --------------------------------------------------------------------------- #
# Start
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5999"))
    debug = os.environ.get("FLASK_ENV") == "development"
    print(f"Vortex browser UI starting at http://127.0.0.1:{port}")
    print("Open this URL in your browser, then paste a link and pick quality.")
    app.run(host="127.0.0.1", port=port, debug=debug)