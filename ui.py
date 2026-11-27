"""Everything that touches the screen."""

from __future__ import annotations

import os
import random
import re
import sys
import time
from urllib.parse import urlparse

from rich import box
from rich.console import Console, Group
from rich.markup import escape
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

import core

VERSION = "2.0.0"

# --------------------------------------------------------------------------- #
# palette
# --------------------------------------------------------------------------- #

ACCENT = "#22d3ee"
ACCENT_SOFT = "#38bdf8"
VIOLET = "#a78bfa"
PINK = "#f472b6"
OK = "#4ade80"
BAD = "#f87171"
WARN = "#fbbf24"
MUTED = "#94a3b8"
FAINT = "#475569"
SURFACE = "#1e293b"
TRACK = "#1e293b"
BORDER = "#334155"

LIGHT_BG = {"white", "yellow", "cyan", MUTED, "#e2e8f0", "#a3e635"}

_URLS = re.compile(r"https?://\S+")

# domain -> (label, colour)
PLATFORMS: dict[str, tuple[str, str]] = {
    "youtube.com": ("YouTube", "#ef4444"),
    "youtu.be": ("YouTube", "#ef4444"),
    "music.youtube.com": ("YouTube Music", "#ef4444"),
    "tiktok.com": ("TikTok", "#ec4899"),
    "instagram.com": ("Instagram", "#d946ef"),
    "instagr.am": ("Instagram", "#d946ef"),
    "twitter.com": ("X", "#334155"),
    "x.com": ("X", "#334155"),
    "facebook.com": ("Facebook", "#2563eb"),
    "fb.watch": ("Facebook", "#2563eb"),
    "reddit.com": ("Reddit", "#f97316"),
    "redd.it": ("Reddit", "#f97316"),
    "vimeo.com": ("Vimeo", "#06b6d4"),
    "twitch.tv": ("Twitch", "#8b5cf6"),
    "soundcloud.com": ("SoundCloud", "#f97316"),
    "dailymotion.com": ("Dailymotion", "#0284c7"),
    "dai.ly": ("Dailymotion", "#0284c7"),
    "pinterest.com": ("Pinterest", "#e11d48"),
    "pin.it": ("Pinterest", "#e11d48"),
    "snapchat.com": ("Snapchat", "#eab308"),
    "linkedin.com": ("LinkedIn", "#0284c7"),
    "threads.net": ("Threads", "#1e293b"),
    "threads.com": ("Threads", "#1e293b"),
    "bsky.app": ("Bluesky", "#0284c7"),
    "bilibili.com": ("Bilibili", "#ec4899"),
    "rumble.com": ("Rumble", "#22c55e"),
    "kick.com": ("Kick", "#22c55e"),
    "odysee.com": ("Odysee", "#ef4444"),
    "streamable.com": ("Streamable", "#06b6d4"),
    "imgur.com": ("Imgur", "#22c55e"),
    "giphy.com": ("Giphy", "#ec4899"),
    "tumblr.com": ("Tumblr", "#2563eb"),
    "vk.com": ("VK", "#2563eb"),
    "ok.ru": ("OK.ru", "#f97316"),
    "weibo.com": ("Weibo", "#ef4444"),
    "nicovideo.jp": ("NicoNico", "#64748b"),
    "9gag.com": ("9GAG", "#334155"),
    "archive.org": ("Archive.org", MUTED),
    "ted.com": ("TED", "#ef4444"),
    "bbc.co.uk": ("BBC", "#ef4444"),
}

STAGE_NAMES = {
    "Merger": "merging",
    "FFmpegMerger": "merging",
    "FFmpegExtractAudio": "extracting audio",
    "FFmpegExtractAudioPP": "extracting audio",
    "EmbedThumbnail": "embedding thumbnail",
    "FFmpegMetadata": "tagging",
    "MetadataParser": "tagging",
    "FFmpegVideoConvertor": "converting",
    "FFmpegVideoRemuxer": "remuxing",
    "MoveFiles": "finalising",
}

LOGO = [
    "██╗   ██╗ ██████╗ ██████╗ ████████╗███████╗██╗  ██╗",
    "██║   ██║██╔═══██╗██╔══██╗╚══██╔══╝██╔════╝╚██╗██╔╝",
    "██║   ██║██║   ██║██████╔╝   ██║   █████╗   ╚███╔╝ ",
    "╚██╗ ██╔╝██║   ██║██╔══██╗   ██║   ██╔══╝   ██╔██╗ ",
    " ╚████╔╝ ╚██████╔╝██║  ██║   ██║   ███████╗██╔╝ ██╗",
    "  ╚═══╝   ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝",
]

TIPS = [
    "paste several links in a row to build a queue",
    "Settings › cookies from browser unlocks private posts",
    "press h for the shortcut sheet, o to open the folder",
    "audio-only saves a fraction of the bytes",
    "Update engine whenever a site changes its plumbing",
    "Enter with no input cancels — nothing is ever half-saved",
]


# --------------------------------------------------------------------------- #
# small formatters
# --------------------------------------------------------------------------- #

def platform(url: str) -> tuple[str, str]:
    host = (urlparse(str(url)).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    best: tuple[str, tuple[str, str]] | None = None
    for domain, meta in PLATFORMS.items():
        if host == domain or host.endswith("." + domain):
            if best is None or len(domain) > len(best[0]):
                best = (domain, meta)
    if best:
        return best[1]
    return (host or "link", MUTED)


def chip(url: str, padded: bool = True) -> str:
    """A little filled badge for the site a link belongs to."""
    name, colour = platform(url)
    foreground = "black" if colour in LIGHT_BG else "white"
    label = escape(short(name, 18))
    if padded:
        return f"[bold {foreground} on {colour}] {label} [/]"
    return f"[bold {foreground} on {colour}]{label}[/]"


def short(text: str, width: int = 40) -> str:
    clean = " ".join(str(text).split())
    return clean if len(clean) <= width else clean[: width - 1] + "…"


def short_path(path, width: int = 40) -> str:
    text = str(path)
    if len(text) <= width:
        return text
    import os
    parts = text.replace("/", os.sep).split(os.sep)
    tail = parts[-1]
    for part in reversed(parts[:-1]):
        candidate = part + os.sep + tail
        if len(candidate) + 2 > width:
            break
        tail = candidate
    return "…" + os.sep + tail


def duration(seconds) -> str:
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return "?"
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def duration_short(seconds) -> str:
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return "0s"
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def human_size(size) -> str:
    try:
        value = float(size or 0)
    except (TypeError, ValueError):
        return "-"
    if value <= 0:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return "-"


def quality_label(quality: str) -> str:
    quality = str(quality or "best").lower()
    if quality == "best":
        return "best"
    if quality == "audio-mp3":
        return "mp3"
    if quality == "audio-m4a":
        return "m4a"
    return f"{quality}p"


def size_bar(size: int, peak: int, width: int = 10) -> Text:
    """Gradient-coloured proportional solid block bar for the quality menu."""
    if not peak or size <= 0:
        return Text("")
    ratio = size / peak
    filled = max(1, round(ratio * width))
    colour = ACCENT if ratio >= 0.75 else ACCENT_SOFT if ratio >= 0.4 else OK
    bar = Text()
    bar.append("█" * filled, style=colour)
    bar.append("█" * (width - filled), style=TRACK)
    return bar


# --------------------------------------------------------------------------- #
# header
# --------------------------------------------------------------------------- #

def _gradient_color(ratio: float) -> str:
    """Interpolate across the horizontal neon spectrum: Cyan -> Sky -> Indigo -> Violet -> Magenta -> Pink."""
    stops = [
        (0.00, (34, 211, 238)),   # #22d3ee cyan
        (0.20, (56, 189, 248)),   # #38bdf8 sky
        (0.40, (129, 140, 248)),  # #818cf8 indigo
        (0.60, (167, 139, 250)),  # #a78bfa violet
        (0.80, (216, 114, 246)),  # #d872f6 magenta
        (1.00, (244, 114, 182)),  # #f472b6 pink
    ]
    ratio = max(0.0, min(1.0, ratio))
    for i in range(len(stops) - 1):
        r1, c1 = stops[i]
        r2, c2 = stops[i + 1]
        if r1 <= ratio <= r2:
            t = (ratio - r1) / (r2 - r1) if r2 > r1 else 0
            r = int(c1[0] + (c2[0] - c1[0]) * t)
            g = int(c1[1] + (c2[1] - c1[1]) * t)
            b = int(c1[2] + (c2[2] - c1[2]) * t)
            return f"#{r:02x}{g:02x}{b:02x}"
    return "#f472b6"


def _logo() -> Text:
    """Horizontal neon gradient across letters: Cyan -> Sky -> Indigo -> Violet -> Magenta -> Pink."""
    text = Text()
    max_len = max(len(line) for line in LOGO) or 1
    for row_idx, line in enumerate(LOGO):
        if row_idx:
            text.append("\n")
        for col_idx, ch in enumerate(line):
            if ch.strip():
                ratio = col_idx / max(1, max_len - 1)
                color = _gradient_color(ratio)
                text.append(ch, style=f"bold {color}")
            else:
                text.append(ch)
    return text


def banner(
    console: Console,
    *,
    engine: str,
    ffmpeg_ok: bool,
    outdir,
    files: int = 0,
    total: int = 0,
    last: str = "",
) -> None:
    ffmpeg_state = (
        Text.assemble(("● ", f"bold {OK}"), ("ready", f"bold {OK}"))
        if ffmpeg_ok
        else Text.assemble(("● ", f"bold {BAD}"), ("missing — install ffmpeg!", f"bold {BAD}"))
    )
    library = (
        f"{files} file{'s' if files != 1 else ''}  ·  {human_size(total)}"
        if files else "empty"
    )

    # Stats grid
    stats = Table.grid(padding=(0, 2))
    stats.add_column(style=MUTED, justify="right", no_wrap=True, width=8)
    stats.add_column(no_wrap=True)
    stats.add_row("engine", Text(f"yt-dlp {engine}", style="white"))
    stats.add_row("ffmpeg", ffmpeg_state)
    stats.add_row("folder", Text(short_path(outdir, 32), style=ACCENT_SOFT))
    stats.add_row("library", Text(library, style="white"))
    if last:
        stats.add_row("last", Text(short(last, 32), style=MUTED))

    # Rotating tip line
    tip = random.choice(TIPS)
    tip_line = Text.assemble(
        (" tip ", f"bold black on {ACCENT}"),
        (f"  {tip}", MUTED),
    )

    # Adaptive layout: side-by-side if terminal is wide enough, stacked if narrow
    if console.width >= 90:
        layout = Table.grid(padding=(0, 2), expand=True)
        layout.add_column(no_wrap=True, width=53)
        layout.add_column(ratio=1, vertical="middle")
        layout.add_row(_logo(), stats)
        content = [layout, Text(""), tip_line]
    else:
        content = [_logo(), Text(""), stats, Text(""), tip_line]

    console.print(Panel(
        Group(*content),
        box=box.ROUNDED,
        border_style=BORDER,
        padding=(0, 2),
        subtitle=f"[{FAINT}]vortex v{VERSION}[/]",
        subtitle_align="right",
    ))
    console.print()


# --------------------------------------------------------------------------- #
# input widgets
# --------------------------------------------------------------------------- #

def menu(console: Console, title: str, rows, prompt: str = "Choose", default=None):
    body = Table.grid(padding=(0, 2))
    body.add_column(width=4, justify="center")
    body.add_column(style="bold white", no_wrap=True)
    body.add_column(style=MUTED, overflow="fold")

    keys: list[str] = []
    for key, label, hint in rows:
        if key is None:
            body.add_row(Text(""), Text(f"  {str(label)}", style=f"bold {FAINT}"), Text(""))
            continue
        key = str(key)
        keys.append(key)
        if key.lower() in {"q", "b"}:
            key_style = f"bold {MUTED} on {SURFACE}"
        elif key.isdigit():
            key_style = f"bold black on {ACCENT}"
        else:
            key_style = f"bold white on {VIOLET}"
        body.add_row(
            Text(f" {key} ", style=key_style),
            escape(str(label)),
            hint if isinstance(hint, Text) else escape(str(hint or "")),
        )

    console.print(Panel(
        body,
        title=f"[bold {ACCENT}]{escape(title)}[/]",
        title_align="left",
        border_style=BORDER,
        box=box.ROUNDED,
        padding=(0, 2),
    ))
    return ask_choice(console, keys, prompt, default=default)


def read_key(console: Console, prompt: str = "") -> str | None:
    """One keystroke, no Enter needed. Falls back to a line read when piped."""
    if not sys.stdin.isatty():
        try:
            raw = console.input(f"{prompt} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return None
        return raw[:1] if raw else ""

    if prompt:
        console.print(prompt, end="")

    try:
        if os.name == "nt":
            import msvcrt
            while True:
                char = msvcrt.getwch()
                if char in ("\x00", "\xe0"):
                    msvcrt.getwch()
                    continue
                break
        else:
            import termios
            import tty
            handle = sys.stdin.fileno()
            saved = termios.tcgetattr(handle)
            try:
                tty.setcbreak(handle)
                char = sys.stdin.read(1)
            finally:
                termios.tcsetattr(handle, termios.TCSADRAIN, saved)
    except KeyboardInterrupt:
        console.print()
        return None

    if char == "\x03":
        console.print()
        raise KeyboardInterrupt
    if char in ("\r", "\n"):
        console.print()
        return ""
    console.print(f"[bold {ACCENT}]{escape(char)}[/]")
    return char.lower()


def ask_choice(console: Console, keys, prompt: str = "Choose", default=None):
    """Returns the chosen key, '' for Enter, or None on Ctrl-C / EOF."""
    keyset = {str(k).lower() for k in keys}
    hint = f" [dim]({'/'.join(sorted(keyset))})[/]" if len(keyset) <= 3 else ""
    while True:
        key = read_key(console, f"[{ACCENT}]›[/] [bold]{prompt}[/]{hint}")
        if key is None:
            return None
        if key == "":
            return default if default is not None else ""
        if key in keyset:
            return key
        console.print(f"[{BAD}]no such key[/] [dim]›[/] {escape(key)}")


def ask_text(console: Console, prompt: str, default: str = "") -> str | None:
    suffix = f" [dim]({escape(str(default))})[/]" if default != "" else ""
    try:
        raw = console.input(f"[{ACCENT}]›[/] [bold]{prompt}[/]{suffix} ").strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return None
    return raw or (str(default) if default != "" else "")


def pause(console: Console, text: str = "press Enter to continue") -> str:
    return read_key(console, f"[dim]{escape(text)}[/]") or ""


def clear_screen(console: Console | None = None) -> None:
    """Reliably clear the terminal screen on Windows and Unix."""
    if sys.platform == "win32" or os.name == "nt":
        os.system("cls")
    elif console is not None:
        console.clear()
    else:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()


# --------------------------------------------------------------------------- #
# panels
# --------------------------------------------------------------------------- #

def metadata_panel(info: dict, url: str) -> Panel:
    _, colour = platform(url)
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=MUTED, justify="right", no_wrap=True)
    grid.add_column(overflow="fold")

    grid.add_row("title", f"[bold]{escape(str(info.get('title') or 'untitled'))}[/]")

    who = info.get("uploader") or info.get("channel") or info.get("creator")
    if who:
        grid.add_row("channel", escape(str(who)))

    bits = []
    if info.get("duration"):
        bits.append(duration(info["duration"]))
    if info.get("view_count"):
        bits.append(f"{int(info['view_count']):,} views")
    if info.get("like_count"):
        bits.append(f"{int(info['like_count']):,} likes")
    if bits:
        grid.add_row("stats", "  ·  ".join(bits))

    uploaded = str(info.get("upload_date") or "")
    if len(uploaded) == 8 and uploaded.isdigit():
        grid.add_row("uploaded", f"{uploaded[:4]}-{uploaded[4:6]}-{uploaded[6:]}")

    if info.get("is_live"):
        grid.add_row("live", f"[bold {BAD}]streaming now[/]")

    heights = core.video_heights(info)
    estimates = core.size_estimates(info)
    if heights:
        biggest = max((e.get("size") or 0 for e in estimates.values()), default=0)
        label = "  ".join(f"{h}p" for h in heights[:8])
        if biggest:
            label += f"  ·  up to {human_size(biggest)}"
        grid.add_row("quality", label)
    elif info.get("formats"):
        grid.add_row("quality", "[dim]audio only[/]")

    if core.is_playlist(info):
        grid.add_row("playlist", f"{core.playlist_count(info)} items")

    description = " ".join(str(info.get("description") or "").split())
    if description:
        description = _URLS.sub("", description)
        description = " ".join(description.split())
        if description:
            grid.add_row("about", f"[dim italic]{escape(short(description, 140))}[/]")

    return Panel(
        grid,
        box=box.ROUNDED,
        border_style=colour,
        padding=(0, 1),
        title=chip(url, padded=False),
        title_align="left",
    )


def queue_panel(jobs, limit: int = 10) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style=MUTED, justify="right", width=3)
    table.add_column(no_wrap=True, width=14)                 # chip — fixed so title col isn't squeezed
    table.add_column(ratio=1, overflow="fold", style="white")
    table.add_column(no_wrap=True, justify="right", style=ACCENT_SOFT)

    for index, (url, quality, label) in enumerate(jobs[:limit], 1):
        table.add_row(
            str(index),
            chip(url),
            escape(short(label or url, 90)),
            quality_label(quality),
        )
    if len(jobs) > limit:
        table.add_row("", "", f"[dim]… {len(jobs) - limit} more[/]", "")

    title = f"[bold {ACCENT}]queue[/] [dim]·[/] {len(jobs)} item{'s' if len(jobs) != 1 else ''}"
    return Panel(table, box=box.ROUNDED, border_style=BORDER,
                 padding=(0, 2), title=title, title_align="left")


def results_panel(results: list[core.DownloadResult], elapsed: float, outdir) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(width=3, justify="center")       # status icon
    table.add_column(no_wrap=True, width=14)           # platform chip — fixed width
    table.add_column(ratio=1, overflow="fold")         # title — takes all remaining space
    table.add_column(no_wrap=True, width=9, justify="right")  # size / short error

    done = 0
    total_bytes = 0
    fresh_bytes = 0
    reused_count = 0

    for result in results:
        ok = result.status == "ok"
        done += int(ok)
        if ok:
            total_bytes += result.size
            if not result.reused:
                fresh_bytes += result.size
        reused_count += int(result.reused)

        # Per-row icon + size/error
        if result.reused:
            icon = Text(" ↺ ", style=f"bold {MUTED}")
            right = Text(human_size(result.size), style=MUTED)
        elif ok:
            icon = Text(" ✓ ", style=f"bold {OK}")
            right = Text(human_size(result.size), style=MUTED)
        else:
            icon = Text(" ✗ ", style=f"bold {BAD}")
            right = Text(short(result.error or "failed", 16), style=BAD)

        table.add_row(
            icon,
            Text.from_markup(chip(result.url)),
            Text(short(result.title or result.url, 60)),
            right,
        )

    if done == len(results):
        colour, verdict = OK, "✓  all done"
    elif done:
        colour, verdict = WARN, "partly done"
    else:
        colour, verdict = BAD, "✗  nothing downloaded"

    footer = Text()
    footer.append(human_size(total_bytes), style="white")
    if fresh_bytes and elapsed > 0.5:
        footer.append("  ·  ", style=FAINT)
        footer.append(f"{human_size(fresh_bytes / elapsed)}/s avg", style="white")
    footer.append("  ·  ", style=FAINT)
    footer.append(duration_short(elapsed), style="white")
    if reused_count:
        footer.append("  ·  ", style=FAINT)
        footer.append(f"{reused_count} already on disk", style=MUTED)
    footer.append("  ·  ", style=FAINT)
    footer.append(short_path(outdir, 20), style=ACCENT_SOFT)

    return Panel(
        Group(table, Text(""), footer),
        box=box.ROUNDED,
        border_style=BORDER,
        padding=(0, 2),
        title=f"[bold {colour}]{verdict}[/]",
        title_align="left",
    )


def error_panel(message: str, subject: str = "", title: str = "link failed",
                hint: str = "") -> Panel:
    body = Text()
    body.append(str(message), style="white")
    if subject:
        body.append("\n")
        body.append(short(subject, 90), style=MUTED)
    if hint:
        body.append("\n\n")
        body.append(hint, style=FAINT)
    return Panel(body, box=box.ROUNDED, border_style=BAD,
                 padding=(0, 1), title=f"[bold {BAD}]{escape(title)}[/]",
                 title_align="left")


def _site_grid() -> Table:
    seen: dict[str, str] = {}
    for label, colour in PLATFORMS.values():
        seen.setdefault(label, colour)

    labels = sorted(seen)
    grid = Table.grid(padding=(0, 1))
    columns = 3
    for _ in range(columns):
        grid.add_column(no_wrap=True)
    for start in range(0, len(labels), columns):
        cells = []
        for label in labels[start:start + columns]:
            colour = seen[label]
            foreground = "black" if colour in LIGHT_BG else "white"
            cells.append(Text(f" {label} ", style=f"{foreground} on {colour}"))
        while len(cells) < columns:
            cells.append(Text(""))
        grid.add_row(*cells)
    return grid


def help_panel() -> Panel:
    keys = Table.grid(padding=(0, 3))
    keys.add_column(no_wrap=True, style=f"bold {ACCENT}")
    keys.add_column(overflow="fold", style="white")
    keys.add_row("download", "paste a link, press Enter, then pick a quality")
    keys.add_row("batch", "paste several links in a row, or load a .txt list")
    keys.add_row("playlist", "choose every entry or just the first")
    keys.add_row("audio", "pick MP3 or M4A from the quality menu")
    keys.add_row("private", "Settings › cookies from browser for Instagram, TikTok, Facebook")
    keys.add_row("script", "python app.py URL -q 1080  ·  -a for mp3  ·  -i to inspect")
    keys.add_row("stuck", "Update engine whenever a site changes its plumbing")

    body = Group(
        keys,
        Text(""),
        Text("supported sites", style=f"bold {VIOLET}"),
        Text(""),
        _site_grid(),
    )
    return Panel(body, box=box.ROUNDED, border_style=BORDER, padding=(0, 2),
                 title=f"[bold {VIOLET}]help[/]", title_align="left")


# --------------------------------------------------------------------------- #
# live download screen & block progress bar
# --------------------------------------------------------------------------- #

class BlockBar:
    """A solid, thick, modern block progress bar matching the reference terminal UI."""

    def __init__(self, completed: float, style: str = ACCENT, track_style: str = TRACK):
        self.completed = max(0.0, min(1.0, float(completed)))
        self.style = style
        self.track_style = track_style

    def __rich_console__(self, console: Console, options):
        width = max(8, options.max_width or 40)
        filled = int(round(self.completed * width))
        empty = max(0, width - filled)

        bar = Text()
        if filled > 0:
            bar.append("█" * filled, style=self.style)
        if empty > 0:
            bar.append("█" * empty, style=self.track_style)
        yield bar


class DownloadScreen:
    """A live view of a running batch: one summary card plus the queue."""

    def __init__(self, jobs):
        self.jobs = [
            {
                "url": url,
                "quality": quality,
                "label": label or url,
                "status": "queued",
                "done": 0,
                "total": 0,
                "size": 0,
                "speed": 0,
                "eta": 0,
                "phase": "",
            }
            for url, quality, label in jobs
        ]
        self.active = -1
        self.started = time.monotonic()
        self.speeds: list[float] = []
        self.last_sample = 0.0

    # -- state, driven by the download hooks ------------------------------
    def start_item(self, index: int) -> None:
        self.active = index
        self.jobs[index]["status"] = "active"
        self.jobs[index]["phase"] = ""

    def progress(self, index: int, done, total, speed=0, eta=0) -> None:
        job = self.jobs[index]
        job["done"] = done or 0
        if total:
            job["total"] = total
        job["speed"] = speed or 0
        job["eta"] = eta or 0
        now = time.monotonic()
        if speed and now - self.last_sample >= 0.5:
            self.speeds.append(float(speed))
            self.last_sample = now
            if len(self.speeds) > 40:
                del self.speeds[:-40]

    def phase(self, index: int, text: str) -> None:
        self.jobs[index]["phase"] = text

    def complete(self, index: int) -> None:
        job = self.jobs[index]
        job["done"] = job["total"] or 1
        job["total"] = job["total"] or 1
        job["speed"] = 0
        job["eta"] = 0

    def finish_item(self, index: int, status: str, size: int = 0) -> None:
        job = self.jobs[index]
        job["status"] = status
        job["size"] = size or job["size"]
        job["speed"] = 0
        job["eta"] = 0
        job["phase"] = ""

    # -- rendering --------------------------------------------------------
    def _finished(self) -> int:
        return sum(1 for j in self.jobs if j["status"] in {"done", "kept", "failed"})

    def _fraction(self) -> float:
        job = self.jobs[self.active] if 0 <= self.active < len(self.jobs) else None
        if not job:
            return 0.0
        if job["status"] in {"done", "kept"}:
            return 1.0
        if job["total"]:
            return max(0.0, min(1.0, job["done"] / job["total"]))
        return 0.0

    def _overall(self) -> float:
        if not self.jobs:
            return 0.0
        done = self._finished()
        job = self.jobs[self.active] if 0 <= self.active < len(self.jobs) else None
        if job and job["status"] == "active":
            done += self._fraction()
        return max(0.0, min(1.0, done / len(self.jobs)))

    def _sparkline(self, values, width: int = 14) -> Text:
        """Tiny bar graph of recent speeds."""
        samples = [float(v or 0) for v in values][-width:]
        if not samples:
            return Text("")
        peak = max(samples) or 1.0
        graph = Text()
        blocks = " ▂▃▄▅▆▇█"
        for value in samples:
            level = int(round((value / peak) * (len(blocks) - 1)))
            style = ACCENT if value > 0 else FAINT
            graph.append(blocks[max(0, min(level, len(blocks) - 1))], style=style)
        return graph

    def _summary(self, width: int) -> Panel:
        job = self.jobs[self.active] if 0 <= self.active < len(self.jobs) else None
        finished = self._finished()
        total_items = len(self.jobs)
        elapsed = max(0.0, time.monotonic() - self.started)

        # Line 1: [Platform] Title on left, Quality · Size on right
        top = Table.grid(padding=(0, 1), expand=True)
        top.add_column(ratio=1, overflow="fold")
        top.add_column(no_wrap=True, justify="right", style=MUTED)

        left_head = Text()
        if job:
            left_head.append_text(Text.from_markup(chip(job["url"])))
            left_head.append("  ")
            left_head.append(short(job["label"], max(24, width - 36)), style="bold white")
        else:
            left_head.append("preparing…", style=f"bold {MUTED}")

        right_head = Text()
        if job:
            right_head.append(quality_label(job["quality"]), style=ACCENT_SOFT)
            if job["total"] > 1024:
                right_head.append("  ·  ", style=FAINT)
                right_head.append(human_size(job["total"]), style="white")

        top.add_row(left_head, right_head)

        # Line 2: Solid Cyan Block Progress Bar + Percentage
        fraction = self._fraction()
        processing = bool(job and job["phase"])
        bar_colour = VIOLET if processing else ACCENT

        bar_grid = Table.grid(padding=(0, 2), expand=True)
        bar_grid.add_column(ratio=1)
        bar_grid.add_column(no_wrap=True, justify="right", width=5)
        bar_grid.add_row(
            BlockBar(fraction, style=bar_colour, track_style=TRACK),
            Text(f"{int(fraction * 100):>3}%", style=f"bold {bar_colour}"),
        )

        # Line 3: Stats on left, Speed Sparkline on right
        stats_grid = Table.grid(padding=(0, 2), expand=True)
        stats_grid.add_column(ratio=1, style="white")
        stats_grid.add_column(no_wrap=True, justify="right")

        stats_left = Text()
        if job and job["status"] == "active":
            if job["phase"]:
                stats_left.append(f" {job['phase']} ", style=f"bold white on {VIOLET}")
                stats_left.append("  ·  ", style=FAINT)
            else:
                if job["total"]:
                    stats_left.append(
                        f"{human_size(job['done'])} / {human_size(job['total'])}",
                        style="white",
                    )
                    stats_left.append("  ·  ", style=FAINT)
                stats_left.append(
                    f"{human_size(job['speed'])}/s" if job["speed"] else "connecting…",
                    style="white" if job["speed"] else MUTED,
                )
                if job["eta"]:
                    stats_left.append("  ·  ", style=FAINT)
                    stats_left.append(f"eta {duration_short(job['eta'])}", style=MUTED)
                stats_left.append("  ·  ", style=FAINT)
        else:
            stats_left.append(f"{finished}/{total_items} files", style=MUTED)
            stats_left.append("  ·  ", style=FAINT)

        stats_left.append(duration_short(elapsed), style=MUTED)

        spark = (
            self._sparkline(self.speeds, width=14)
            if (job and job["status"] == "active" and len(self.speeds) > 2)
            else Text("")
        )
        stats_grid.add_row(stats_left, spark)

        parts: list = [top, bar_grid, stats_grid]

        # Line 4: Batch progress bar (if multiple items)
        if total_items > 1:
            overall = self._overall()
            batch_grid = Table.grid(padding=(0, 2), expand=True)
            batch_grid.add_column(no_wrap=True, style=MUTED, width=6)
            batch_grid.add_column(ratio=1)
            batch_grid.add_column(no_wrap=True, justify="right", width=5)
            batch_grid.add_column(no_wrap=True, justify="right", width=6, style=MUTED)
            batch_grid.add_row(
                Text("batch", style=MUTED),
                BlockBar(overall, style=ACCENT_SOFT, track_style=TRACK),
                Text(f"{int(overall * 100):>3}%", style=f"bold {ACCENT_SOFT}"),
                Text(f"{finished}/{total_items}", style=MUTED),
            )
            parts.append(batch_grid)

        count = min(finished + (1 if job else 0), total_items)
        title = f"[{MUTED}]downloading[/] [dim]·[/] [{ACCENT}]{count}/{total_items}[/]"
        return Panel(
            Group(*parts),
            box=box.ROUNDED,
            border_style=BORDER,
            padding=(0, 2),
            title=title,
            title_align="left",
        )

    def _queue(self) -> Panel:
        table = Table.grid(padding=(0, 2), expand=True)
        table.add_column(width=2, justify="center")          # status dot
        table.add_column(no_wrap=True, width=13)             # platform chip
        table.add_column(ratio=1, overflow="fold")           # title
        table.add_column(no_wrap=True, justify="right", width=8, style=MUTED)  # quality
        table.add_column(no_wrap=True, justify="right", width=8)               # status text

        count = len(self.jobs)
        if count <= 10:
            start, end = 0, count
        else:
            start = max(0, self.active - 4)
            end = min(count, start + 10)
            start = max(0, end - 10)

        if start > 0:
            table.add_row("", "", f"[dim]… {start} more above[/]", "", "")

        for index in range(start, end):
            job = self.jobs[index]
            status = job["status"]
            if status == "done":
                dot = Text("●", style=f"bold {OK}")
                status_text = Text("done", style=f"bold {OK}")
                label_style = "white"
            elif status == "kept":
                dot = Text("●", style=f"bold {MUTED}")
                status_text = Text("on disk", style=f"dim {MUTED}")
                label_style = "white"
            elif status == "failed":
                dot = Text("●", style=f"bold {BAD}")
                status_text = Text("failed", style=f"bold {BAD}")
                label_style = "white"
            elif status == "active":
                dot = Text("●", style=f"bold {ACCENT}")
                if job["total"]:
                    pct = int(100 * job["done"] / job["total"])
                    status_text = Text(f"{pct}%", style=f"bold {ACCENT}")
                elif job["phase"]:
                    status_text = Text(job["phase"], style=f"bold {VIOLET}")
                else:
                    status_text = Text("…", style=f"bold {ACCENT}")
                label_style = "bold white"
            else:  # queued
                dot = Text("·", style=f"bold {FAINT}")
                status_text = Text("queued", style=f"dim {FAINT}")
                label_style = "dim white"

            table.add_row(
                dot,
                Text.from_markup(chip(job["url"])),
                Text(short(job["label"], 50), style=label_style),
                quality_label(job["quality"]),
                status_text,
            )

        if end < count:
            table.add_row("", "", f"[dim]… {count - end} more below[/]", "", "")

        title = f"[{MUTED}]queue[/]"
        return Panel(
            table,
            box=box.ROUNDED,
            border_style=BORDER,
            padding=(0, 2),
            title=title,
            title_align="left",
        )

    def __rich_console__(self, console, options):
        yield self._summary(options.max_width)
        if len(self.jobs) > 1:
            yield Text("")
            yield self._queue()

