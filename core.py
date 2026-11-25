"""Download engine: a small, opinionated wrapper around yt-dlp."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

import config

ProgressCb = Callable[[dict], None]

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


class ProbeError(RuntimeError):
    """Raised when a link cannot be read."""


class _QuietLogger:
    """Swallow yt-dlp's own console chatter; vd renders everything itself."""

    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


@dataclass
class DownloadResult:
    url: str
    title: str
    path: Path | None
    size: int
    status: str          # ok | failed | cancelled
    error: str = ""
    reused: bool = False  # file was already on disk


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def clean_error(message: str) -> str:
    text = _ANSI.sub("", message or "").replace("ERROR: ", "").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(lines[:3])[:400] or "unknown error"


def parse_rate(text) -> float | None:
    """'5M' -> bytes per second. Blank or junk -> None (unlimited)."""
    if not text:
        return None
    raw = str(text).strip().lower().replace(" ", "")
    if not raw:
        return None
    mult = 1
    for suffix, factor in (("g", 1 << 30), ("m", 1 << 20), ("k", 1 << 10)):
        if raw.endswith(suffix):
            mult = factor
            raw = raw[:-1]
            break
    try:
        value = float(raw) * mult
    except ValueError:
        return None
    return value if value > 0 else None


def normalize_quality(text) -> str | None:
    if text is None:
        return None
    raw = str(text).strip().lower()
    if not raw:
        return None
    if raw in {"mp3", "audio", "audio-mp3", "a"}:
        return "audio-mp3"
    if raw in {"m4a", "audio-m4a"}:
        return "audio-m4a"
    if raw in {"best", "b"}:
        return "best"
    if raw.endswith("p"):
        raw = raw[:-1]
    if raw.isdigit():
        height = int(raw)
        if 144 <= height <= 4320:
            return str(height)
    return None


def format_spec(quality: str) -> tuple[str, str | None]:
    """Map a quality token to (yt-dlp format selector, audio codec or None).

    MP4/M4A pairs are preferred so the merged file lands as .mp4; anything
    that only exists as VP9/AV1/Opus simply stays in its native container.
    """
    quality = (quality or "best").lower()
    if quality == "audio-mp3":
        return "bestaudio/best", "mp3"
    if quality == "audio-m4a":
        return "bestaudio[ext=m4a]/bestaudio/best", "m4a"
    if quality.isdigit():
        height = int(quality)
        return (
            f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]"
            f"/b[height<={height}][ext=mp4]"
            f"/bv*[height<={height}]+ba/b[height<={height}]/b",
            None,
        )
    return "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b", None


def is_playlist(info: dict) -> bool:
    return info.get("_type") == "playlist" or bool(info.get("entries"))


def playlist_count(info: dict) -> int:
    return int(info.get("playlist_count") or len(info.get("entries") or []) or 0)


def playlist_urls(info: dict) -> list[str]:
    """Pull individual video URLs out of a playlist result."""
    urls: list[str] = []
    engine = str(info.get("extractor_key") or info.get("ie_key") or "").lower()
    for entry in info.get("entries") or []:
        if not entry:
            continue
        url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
        if not url:
            continue
        if not url.startswith("http"):
            video_id = entry.get("id") or url
            if "youtube" in engine:
                url = f"https://www.youtube.com/watch?v={video_id}"
            else:
                continue
        urls.append(url)
    return urls


def video_heights(info: dict) -> list[int]:
    heights = set()
    for fmt in info.get("formats") or []:
        if fmt.get("vcodec") in (None, "none"):
            continue
        height = fmt.get("height")
        if isinstance(height, int) and height >= 144:
            heights.add(height)
    own = info.get("height")
    if isinstance(own, int) and own >= 144:
        heights.add(own)
    return sorted(heights, reverse=True)


def size_estimates(info: dict) -> dict[int, dict]:
    """Rough download size per resolution, so the menu can show numbers."""
    formats = info.get("formats") or []

    audio_size = 0
    for fmt in formats:
        if fmt.get("vcodec") in (None, "none") and fmt.get("acodec") not in (None, "none"):
            size = fmt.get("filesize") or fmt.get("filesize_approx") or 0
            audio_size = max(audio_size, size)

    estimates: dict[int, dict] = {}
    for fmt in formats:
        height = fmt.get("height")
        if not isinstance(height, int) or height < 144:
            continue
        if fmt.get("vcodec") in (None, "none"):
            continue
        size = fmt.get("filesize") or fmt.get("filesize_approx") or 0
        if not size:
            continue
        # progressive files already contain audio
        total = size if fmt.get("acodec") not in (None, "none") else size + audio_size
        current = estimates.get(height)
        if current is None or total > current.get("size", 0):
            estimates[height] = {
                "size": total,
                "fps": fmt.get("fps"),
                "ext": fmt.get("ext"),
            }
    return estimates


# --------------------------------------------------------------------------- #
# yt-dlp plumbing
# --------------------------------------------------------------------------- #

def _base_opts(cfg: dict) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _QuietLogger(),
        "noplaylist": True,
        "ignoreerrors": False,
        "retries": 10,
        "fragment_retries": 10,
        "socket_timeout": 30,
        "windowsfilenames": True,
        "concurrent_fragment_downloads": max(1, int(cfg.get("concurrent_fragments", 4) or 4)),
        "continuedl": True,
        "overwrites": False,
    }
    browser = str(cfg.get("cookies_browser") or "").strip().lower()
    if browser and browser != "none":
        opts["cookiesfrombrowser"] = (browser,)
    proxy = str(cfg.get("proxy") or "").strip()
    if proxy:
        opts["proxy"] = proxy
    rate = parse_rate(cfg.get("rate_limit"))
    if rate:
        opts["ratelimit"] = rate
    return opts


def probe(url: str, cfg: dict) -> dict:
    """Read metadata for a link without downloading anything."""
    opts = _base_opts(cfg)
    opts["skip_download"] = True
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        raise ProbeError(clean_error(str(exc))) from exc
    except Exception as exc:  # network, DNS, bad URL
        raise ProbeError(clean_error(f"{type(exc).__name__}: {exc}")) from exc
    if not info:
        raise ProbeError("no media found at that link")
    return info


def _final_path(info: dict) -> Path | None:
    candidates: list[str] = []
    for item in info.get("requested_downloads") or []:
        for key in ("filepath", "_filename", "filename"):
            if item.get(key):
                candidates.append(item[key])
    for key in ("filepath", "_filename"):
        if info.get(key):
            candidates.append(info[key])
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return path
    return None


def _newest_file(folder: Path, since: float) -> Path | None:
    skip = {".part", ".ytdl", ".webp", ".jpg", ".png", ".vtt", ".srt", ".temp"}
    best: tuple[float, Path] | None = None
    try:
        entries = list(folder.iterdir())
    except OSError:
        return None
    for path in entries:
        try:
            if not path.is_file() or path.suffix.lower() in skip:
                continue
            stamp = path.stat().st_mtime
        except OSError:
            continue
        if stamp + 1 < since:
            continue
        if best is None or stamp > best[0]:
            best = (stamp, path)
    return best[1] if best else None


def download(
    url: str,
    cfg: dict,
    quality: str = "best",
    on_progress: ProgressCb | None = None,
    on_stage: ProgressCb | None = None,
) -> DownloadResult:
    """Download one link and return where it landed."""
    started = time.time()
    selector, audio_codec = format_spec(quality)
    outdir = config.download_dir(cfg)
    outdir.mkdir(parents=True, exist_ok=True)
    template = cfg.get("filename_template") or config.DEFAULTS["filename_template"]

    opts = _base_opts(cfg)
    opts.update({
        "format": selector,
        "outtmpl": {"default": str(outdir / template)},
        "noplaylist": True,
        "progress_hooks": [on_progress] if on_progress else [],
        "postprocessor_hooks": [on_stage] if on_stage else [],
    })

    postprocessors = []
    if audio_codec:
        postprocessors.append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": audio_codec,
            "preferredquality": "192" if audio_codec == "mp3" else "0",
        })
    if cfg.get("embed_metadata", True):
        postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
    if cfg.get("embed_thumbnail", True):
        opts["writethumbnail"] = True
        postprocessors.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})
    if cfg.get("subtitles", False):
        opts.update({
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en.*"],
            "subtitlesformat": "srt/best",
        })
    if postprocessors:
        opts["postprocessors"] = postprocessors

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except DownloadError as exc:
        return DownloadResult(url, url, None, 0, "failed", clean_error(str(exc)))
    except Exception as exc:
        return DownloadResult(url, url, None, 0, "failed",
                              clean_error(f"{type(exc).__name__}: {exc}"))

    if not info:
        return DownloadResult(url, url, None, 0, "failed", "no media found")

    path = _final_path(info) or _newest_file(outdir, started)
    size = path.stat().st_size if path and path.exists() else 0
    reused = bool(path and path.exists() and path.stat().st_mtime + 2 < started)
    return DownloadResult(
        url=url,
        title=info.get("title") or url,
        path=path,
        size=size,
        status="ok" if path else "failed",
        error="" if path else "download finished but the file could not be located",
        reused=reused,
    )
