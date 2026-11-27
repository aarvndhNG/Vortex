"""Vortex — high-speed terminal media downloader."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import config
import core
import ui

VERSION = "2.0.0"
console = Console()

EXAMPLES = """examples:
  vortex                                 open the interactive menu
  vortex https://youtu.be/XXXX           best quality
  vortex URL1 URL2 -q 720                batch at 720p
  vortex URL -a                          audio only, mp3
  vortex URL -i                          inspect metadata without downloading
  vortex URL -o ~/videos --cookies chrome
"""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def engine_version() -> str:
    try:
        from yt_dlp.version import __version__
        return __version__
    except Exception:
        return "unknown"


def ffmpeg_ready() -> bool:
    return shutil.which("ffmpeg") is not None


def onoff(value) -> str:
    return "on" if value else "off"


def folder_stats(cfg: dict) -> tuple[int, int]:
    folder = config.download_dir(cfg)
    count = 0
    total = 0
    try:
        for entry in folder.iterdir():
            if not entry.is_file():
                continue
            if entry.suffix.lower() in {".part", ".ytdl"}:
                continue
            count += 1
            try:
                total += entry.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return count, total


def _ago(stamp: str) -> str:
    try:
        moment = datetime.strptime(str(stamp), "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return "recently"
    minutes = int((datetime.now() - moment).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    if minutes < 1440:
        return f"{minutes // 60}h ago"
    return f"{minutes // 1440}d ago"


def last_download() -> str:
    entries = config.load_history()
    if not entries:
        return ""
    entry = entries[-1]
    title = ui.short(entry.get("title") or "something", 26)
    return f"{title}  ·  {_ago(entry.get('time', ''))}"


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError as exc:
        console.print(ui.error_panel(str(exc), str(path), "cannot open folder"))


# --------------------------------------------------------------------------- #
# quality pickers
# --------------------------------------------------------------------------- #

def choose_quality(cfg: dict, info: dict, prompt: str = "Quality") -> str | None:
    """Quality menu built from this video's real streams, with size guesses."""
    heights = core.video_heights(info)
    estimates = core.size_estimates(info)

    rows: list[tuple[str, str, object]] = []
    mapping: dict[str, str] = {}

    biggest = max((e.get("size") or 0 for e in estimates.values()), default=0)

    best_hint = Text()
    if heights:
        best_hint.append(f"up to {heights[0]}p", style=ui.MUTED)
    if biggest:
        if heights:
            best_hint.append("  ·  ", style=ui.FAINT)
        best_hint.append_text(ui.size_bar(biggest, biggest))
        best_hint.append(f"  {ui.human_size(biggest)}", style="white")
    if not heights and not biggest:
        best_hint.append("highest video + best audio", style=ui.MUTED)
    rows.append(("1", "Best available", best_hint))
    mapping["1"] = "best"

    index = 2
    for height in heights:
        meta = estimates.get(height, {})
        hint = Text()
        if meta.get("fps"):
            hint.append(f"{int(meta['fps'])} fps  ·  ", style=ui.MUTED)
        size = meta.get("size") or 0
        if size and biggest:
            hint.append_text(ui.size_bar(size, biggest))
            hint.append(f"  {ui.human_size(size)}", style="white")
        if meta.get("ext"):
            if hint.plain:
                hint.append("  ·  ", style=ui.FAINT)
            hint.append(str(meta["ext"]).upper(), style=ui.FAINT)
        if height == 1080 and heights[0] > 1080:
            hint.append("  ★", style=ui.OK)
        rows.append((str(index), f"{height}p", hint))
        mapping[str(index)] = str(height)
        index += 1
        if index > 8:
            break

    rows.append((str(index), "Audio only · MP3", "192 kbps"))
    mapping[str(index)] = "audio-mp3"
    index += 1
    rows.append((str(index), "Audio only · M4A", "best quality, smallest audio"))
    mapping[str(index)] = "audio-m4a"

    pick = ui.menu(console, prompt, rows, prompt="Pick", default="1")
    if pick == "":
        pick = "1"
    if pick is None:
        return None
    return mapping.get(pick)


def choose_quality_static(cfg: dict, prompt: str = "Quality for all") -> str | None:
    rows = [
        ("1", "Best available", "highest video + best audio"),
        ("2", "2160p", "4K"),
        ("3", "1440p", "2K"),
        ("4", "1080p", "full HD"),
        ("5", "720p", "HD"),
        ("6", "480p", ""),
        ("7", "360p", "smallest video"),
        ("8", "Audio only · MP3", "192 kbps"),
        ("9", "Audio only · M4A", "best quality, smallest audio"),
    ]
    mapping = {
        "1": "best", "2": "2160", "3": "1440", "4": "1080", "5": "720",
        "6": "480", "7": "360", "8": "audio-mp3", "9": "audio-m4a",
    }
    pick = ui.menu(console, prompt, rows, prompt="Pick", default="1")
    if pick == "":
        pick = "1"
    if pick is None:
        return None
    return mapping.get(pick)


# --------------------------------------------------------------------------- #
# downloading
# --------------------------------------------------------------------------- #

def _hooks(screen: ui.DownloadScreen, index: int):
    def on_progress(data: dict) -> None:
        status = data.get("status")
        if status == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            screen.progress(
                index,
                data.get("downloaded_bytes") or 0,
                total,
                data.get("speed") or 0,
                data.get("eta") or 0,
            )
        elif status == "finished":
            screen.phase(index, "processing")

    def on_stage(data: dict) -> None:
        if data.get("status") != "started":
            return
        stage = ui.STAGE_NAMES.get(str(data.get("postprocessor") or ""))
        if stage:
            screen.phase(index, stage)

    return on_progress, on_stage


def download_jobs(cfg: dict, jobs: list[tuple[str, str, str]]):
    """Run (url, quality, label) jobs in order. Returns (results, elapsed)."""
    started = time.monotonic()
    results: list[core.DownloadResult] = []
    screen = ui.DownloadScreen(jobs)

    with Live(screen, console=console, refresh_per_second=8, transient=False):
        for index, (url, quality, label) in enumerate(jobs):
            screen.start_item(index)
            on_progress, on_stage = _hooks(screen, index)

            try:
                result = core.download(url, cfg, quality,
                                       on_progress=on_progress, on_stage=on_stage)
            except KeyboardInterrupt:
                screen.finish_item(index, "failed")
                results.append(core.DownloadResult(url, label or url, None, 0,
                                                   "cancelled", "cancelled by user"))
                break

            if result.status == "ok":
                status = "kept" if result.reused else "done"
            else:
                status = "failed"
                console.print(f"[{ui.BAD}]![/] {escape(ui.short(result.error, 160))}")

            screen.complete(index)
            screen.finish_item(index, status, result.size)

            results.append(result)
            config.add_history({
                "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "url": url,
                "title": result.title,
                "platform": ui.platform(url)[0],
                "path": str(result.path) if result.path else "",
                "size": result.size,
                "status": result.status,
            })

    return results, time.monotonic() - started


def show_results(cfg: dict, results: list[core.DownloadResult], elapsed: float) -> None:
    if not results:
        return
    console.print()
    console.print(ui.results_panel(results, elapsed, config.download_dir(cfg)))


# --------------------------------------------------------------------------- #
# interactive actions
# --------------------------------------------------------------------------- #

def collect_links() -> list[str]:
    console.print("[dim]Paste a link and press Enter. Add more, or leave blank to start.[/]")
    links: list[str] = []
    while True:
        try:
            raw = console.input(f"[{ui.ACCENT}]{len(links) + 1:>2}[/] [dim]>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return links
        if not raw:
            return links
        for part in re.split(r"\s+", raw):
            part = part.strip().strip(",;'\"")
            if re.match(r"^https?://", part, re.I):
                links.append(part)
            elif part:
                console.print(f"[{ui.WARN}]skip[/] {escape(ui.short(part, 60))} [dim]not a link[/]")


def run_batch(cfg: dict, links: list[str]) -> None:
    links = [link for link in links if link]
    if not links:
        return

    single = len(links) == 1
    batch_quality: str | None = None
    if not single:
        batch_quality = choose_quality_static(cfg)
        if batch_quality is None:
            return

    jobs: list[tuple[str, str, str]] = []

    for url in links:
        try:
            with console.status(
                f"[{ui.ACCENT}]reading[/] {ui.chip(url)} [dim]{escape(ui.short(url, 46))}[/]",
                spinner="dots",
            ):
                info = core.probe(url, cfg)
        except core.ProbeError as exc:
            console.print(ui.error_panel(
                str(exc), url,
                hint="if this used to work, try Update engine from the menu",
            ))
            continue

        if core.is_playlist(info):
            console.print(ui.metadata_panel(info, url))
            count = core.playlist_count(info)
            pick = ui.menu(console, "playlist", [
                ("1", f"Download all {count} items", "adds every entry to the queue"),
                ("2", "Just the first item", ""),
                ("3", "Skip it", ""),
            ], prompt="Playlist")
            if pick in (None, "3", ""):
                continue
            quality = batch_quality or choose_quality(cfg, info, "Quality for this playlist")
            if quality is None:
                continue
            with console.status("[cyan]expanding playlist…", spinner="dots"):
                entries = core.playlist_urls(info)
            if not entries:
                console.print(f"[{ui.WARN}]playlist had no usable entries[/]")
                continue
            if pick == "2":
                entries = entries[:1]
            jobs.extend((entry, quality, "") for entry in entries)
        else:
            if single:
                console.print(ui.metadata_panel(info, url))
                quality = choose_quality(cfg, info)
                if quality is None:
                    continue
            else:
                quality = batch_quality or cfg.get("default_quality", "best")
                console.print(
                    f"[{ui.OK}]+[/] {escape(ui.short(info.get('title') or url, 68))}"
                )
            jobs.append((url, quality, str(info.get("title") or "")))

    if not jobs:
        console.print(f"[{ui.WARN}]nothing queued[/]")
        return

    results, elapsed = download_jobs(cfg, jobs)
    show_results(cfg, results, elapsed)


def action_links(cfg: dict) -> None:
    ui.clear_screen(console)
    links = collect_links()
    if links:
        run_batch(cfg, links)
        if ui.pause(console, "press any key  ·  o opens the folder") == "o":
            open_folder(config.download_dir(cfg))
    else:
        ui.pause(console)


def action_file(cfg: dict) -> None:
    ui.clear_screen(console)
    raw = ui.ask_text(console, "path to a .txt list of links")
    if raw is None:
        return
    raw = raw.strip().strip('"')
    if not raw:
        return
    path = Path(raw)
    if not path.is_absolute():
        path = config.BASE_DIR / path
    if not path.exists():
        console.print(ui.error_panel("no such file", str(path), "cannot read list"))
        ui.pause(console)
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError as exc:
        console.print(ui.error_panel(str(exc), str(path), "cannot read list"))
        ui.pause(console)
        return
    links = [line.strip() for line in lines
             if line.strip() and not line.strip().startswith("#")
             and re.match(r"^https?://", line.strip(), re.I)]
    if not links:
        console.print(f"[{ui.WARN}]no links in that file[/]")
        ui.pause(console)
        return
    console.print(f"[{ui.OK}]{len(links)}[/] links found")
    run_batch(cfg, links)
    ui.pause(console)


def action_history(cfg: dict) -> None:
    ui.clear_screen(console)
    entries = config.load_history()
    if not entries:
        console.print(Panel(
            Text.assemble(
                ("nothing here yet", "bold white"),
                ("\n", ""),
                ("downloads land here so you can re-run one with a single key", ui.MUTED),
            ),
            box=box.ROUNDED, border_style=ui.FAINT, padding=(0, 2),
            title=f"[bold {ui.ACCENT}]history[/]", title_align="left",
        ))
        ui.pause(console)
        return

    recent = entries[-25:]
    table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {ui.ACCENT}", expand=True)
    table.add_column("#", width=3, justify="right", style=ui.MUTED)
    table.add_column("when", width=8, style=ui.MUTED)
    table.add_column("site", width=14, no_wrap=True)
    table.add_column("title", ratio=1, min_width=20, overflow="fold")
    table.add_column("size", width=8, justify="right")
    table.add_column("", width=2, justify="center")
    for index, entry in enumerate(recent, 1):
        ok = entry.get("status") == "ok"
        table.add_row(
            str(index),
            _ago(entry.get("time", "")),
            escape(str(entry.get("platform", ""))),
            escape(ui.short(entry.get("title", ""), 70)),
            ui.human_size(entry.get("size")),
            f"[{ui.OK if ok else ui.BAD}]●[/]",
        )

    total_bytes = sum(int(entry.get("size") or 0) for entry in entries)
    footer = Text.assemble(
        (f"{len(entries)} download{'s' if len(entries) != 1 else ''}", f"bold {ui.ACCENT}"),
        ("  ·  ", ui.FAINT),
        (ui.human_size(total_bytes), "white"),
        ("  ·  ", ui.FAINT),
        (f"newest {_ago(entries[-1].get('time', ''))}", ui.MUTED),
    )
    console.print(Panel(
        Group(table, Text(""), footer),
        box=box.ROUNDED, border_style=ui.FAINT, padding=(0, 1),
        title=f"[bold {ui.ACCENT}]history[/] [dim]·[/] last {len(recent)}",
        title_align="left",
    ))

    pick = ui.menu(console, "history", [
        ("o", "Open downloads folder", ""),
        ("r", "Download one again", ""),
        ("c", "Clear history", ""),
        ("b", "Back", ""),
    ], prompt="History")

    if pick in (None, "b", ""):
        return

    if pick == "o":
        open_folder(config.download_dir(cfg))
        ui.pause(console)
    elif pick == "r":
        number = ui.ask_text(console, f"number 1-{len(recent)}")
        try:
            entry = recent[int(str(number)) - 1]
        except (TypeError, ValueError, IndexError):
            console.print(f"[{ui.BAD}]that isn't in the list[/]")
            ui.pause(console)
            return
        run_batch(cfg, [str(entry.get("url", ""))])
        ui.pause(console)
    elif pick == "c":
        if ui.ask_choice(console, ["y", "n"], "clear all history?") == "y":
            config.clear_history()
            console.print(f"[{ui.OK}]history cleared[/]")
        ui.pause(console)


def action_settings(cfg: dict) -> None:
    browsers = {
        "0": "", "1": "chrome", "2": "edge", "3": "firefox",
        "4": "brave", "5": "opera", "6": "vivaldi", "7": "safari",
    }

    while True:
        ui.clear_screen(console)
        rows = [
            (None, "where things go", ""),
            ("1", "Download folder", ui.short_path(config.download_dir(cfg), 42)),
            ("2", "Filename template", ui.short(cfg["filename_template"], 44)),
            ("3", "Default quality", str(cfg["default_quality"])),
            (None, "network", ""),
            ("4", "Cookies from browser", str(cfg["cookies_browser"] or "off")),
            ("5", "Proxy", str(cfg["proxy"] or "off")),
            ("6", "Speed limit", str(cfg["rate_limit"] or "unlimited")),
            (None, "after the download", ""),
            ("7", "Embed metadata", onoff(cfg["embed_metadata"])),
            ("8", "Embed thumbnail", onoff(cfg["embed_thumbnail"])),
            ("9", "Download subtitles", onoff(cfg["subtitles"])),
            ("b", "Back", ""),
        ]
        pick = ui.menu(console, "settings", rows, prompt="Change")
        if pick in (None, "b", ""):
            return

        changed = True
        if pick == "1":
            value = ui.ask_text(console, "download folder", str(config.download_dir(cfg)))
            if value:
                cfg["download_dir"] = value
            else:
                changed = False
        elif pick == "2":
            console.print(f"[dim]fields:[/] [{ui.ACCENT_SOFT}]%(title)s %(uploader)s "
                          f"%(id)s %(ext)s %(upload_date)s[/]")
            value = ui.ask_text(console, "filename template", cfg["filename_template"])
            if value:
                cfg["filename_template"] = value
            else:
                changed = False
        elif pick == "3":
            value = ui.ask_text(
                console,
                "quality (best / 2160 / 1440 / 1080 / 720 / 480 / 360 / mp3 / m4a)",
                cfg["default_quality"],
            )
            quality = core.normalize_quality(value)
            if quality:
                cfg["default_quality"] = quality
            else:
                console.print(f"[{ui.BAD}]unrecognised quality[/]")
                changed = False
        elif pick == "4":
            choice = ui.menu(console, "cookies from browser", [
                ("0", "Off", "no cookies"),
                ("1", "Chrome", "needed for most private posts"),
                ("2", "Edge", ""),
                ("3", "Firefox", ""),
                ("4", "Brave", ""),
                ("5", "Opera", ""),
                ("6", "Vivaldi", ""),
                ("7", "Safari", ""),
            ], prompt="Browser")
            if choice in browsers:
                cfg["cookies_browser"] = browsers[choice]
            else:
                changed = False
        elif pick == "5":
            value = ui.ask_text(console, "proxy url, e.g. http://127.0.0.1:8080",
                                cfg["proxy"] or "")
            if value is not None:
                cfg["proxy"] = value.strip()
            else:
                changed = False
        elif pick == "6":
            value = ui.ask_text(console, "speed limit, e.g. 5M  (blank = unlimited)",
                                cfg["rate_limit"] or "")
            if value is not None:
                cfg["rate_limit"] = value.strip()
            else:
                changed = False
        elif pick == "7":
            cfg["embed_metadata"] = not cfg["embed_metadata"]
        elif pick == "8":
            cfg["embed_thumbnail"] = not cfg["embed_thumbnail"]
        elif pick == "9":
            cfg["subtitles"] = not cfg["subtitles"]

        if changed:
            config.save(cfg)
            console.print(f"[{ui.OK}]saved[/]")
        ui.pause(console, "press any key")


def action_update() -> None:
    ui.clear_screen(console)
    console.print("[dim]asking pip to upgrade yt-dlp…[/]")
    try:
        with console.status(f"[{ui.ACCENT}]updating[/]", spinner="dots"):
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", "yt-dlp"],
                capture_output=True, text=True,
            )
    except OSError as exc:
        console.print(ui.error_panel(str(exc), "", "could not run pip"))
        ui.pause(console)
        return

    if proc.returncode == 0:
        console.print(f"[{ui.OK}]engine updated[/]")
    else:
        output = (proc.stderr or proc.stdout or "").strip()[-1500:]
        console.print(ui.error_panel(output or "pip failed", "", "update failed"))
    console.print(f"[dim]installed:[/] yt-dlp {engine_version()}")
    ui.pause(console)


def action_help() -> None:
    ui.clear_screen(console)
    console.print(ui.help_panel())
    ui.pause(console)


def action_open(cfg: dict) -> None:
    folder = config.download_dir(cfg)
    open_folder(folder)
    console.print(f"[{ui.ACCENT_SOFT}]{escape(str(folder))}[/]")
    ui.pause(console)


# --------------------------------------------------------------------------- #
# entry points
# --------------------------------------------------------------------------- #

def interactive(cfg: dict) -> None:
    while True:
        ui.clear_screen(console)
        files, total = folder_stats(cfg)
        ui.banner(
            console,
            engine=engine_version(),
            ffmpeg_ok=ffmpeg_ready(),
            outdir=config.download_dir(cfg),
            files=files,
            total=total,
            last=last_download(),
        )
        choice = ui.menu(console, "main", [
            (None, "download", ""),
            ("1", "Download", "one link, several links, or a playlist"),
            ("2", "From a file", "batch from a .txt list"),
            (None, "library", ""),
            ("3", "History", "review past downloads"),
            ("4", "Settings", "folder, quality, cookies, limits"),
            ("o", "Open folder", "explorer at the download directory"),
            (None, "system", ""),
            ("5", "Update engine", "refresh yt-dlp extractors"),
            ("h", "Help", "supported sites and shortcuts"),
            ("q", "Quit", ""),
        ])

        if choice is None:
            console.print("[dim]bye[/]")
            return
        if choice == "q":
            console.print("[dim]bye[/]")
            return
        if choice == "":
            continue

        try:
            if choice == "1":
                action_links(cfg)
            elif choice == "2":
                action_file(cfg)
            elif choice == "3":
                action_history(cfg)
            elif choice == "4":
                action_settings(cfg)
            elif choice == "5":
                action_update()
            elif choice == "h":
                action_help()
            elif choice == "o":
                action_open(cfg)
        except KeyboardInterrupt:
            console.print(f"\n[{ui.WARN}]cancelled[/]")


def cli(cfg: dict, args) -> int:
    if args.info:
        for url in args.urls:
            try:
                with console.status(
                    f"[{ui.ACCENT}]reading[/] {ui.chip(url)} [dim]{escape(ui.short(url, 46))}[/]",
                    spinner="dots",
                ):
                    info = core.probe(url, cfg)
            except core.ProbeError as exc:
                console.print(ui.error_panel(
                    str(exc), url,
                    hint="if this used to work, try Update engine from the menu",
                ))
                return 1
            console.print(ui.metadata_panel(info, url))
        return 0

    quality = "audio-mp3" if args.audio else (
        core.normalize_quality(args.quality) or cfg.get("default_quality", "best")
    )
    console.print(
        f"  [{ui.MUTED}]quality[/] [{ui.ACCENT}]{ui.quality_label(quality)}[/]"
        f"   [{ui.MUTED}]into[/] [{ui.ACCENT_SOFT}]{escape(str(config.download_dir(cfg)))}[/]"
    )
    console.print()

    jobs = [(url, quality, "") for url in args.urls]
    results, elapsed = download_jobs(cfg, jobs)
    show_results(cfg, results, elapsed)
    return 0 if results and all(r.status == "ok" for r in results) else 1


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="vortex",
        description="Vortex — High-speed terminal media downloader.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("urls", nargs="*", help="one or more links")
    parser.add_argument("-q", "--quality",
                        help="best, 2160, 1440, 1080, 720, 480, 360, mp3, m4a")
    parser.add_argument("-a", "--audio", action="store_true", help="audio only (mp3)")
    parser.add_argument("-o", "--output", help="download folder")
    parser.add_argument("--cookies", help="read cookies from this browser")
    parser.add_argument("--no-thumbnail", action="store_true", help="don't embed thumbnails")
    parser.add_argument("--no-metadata", action="store_true", help="don't write tags")
    parser.add_argument("-i", "--info", action="store_true",
                        help="print metadata only, download nothing")
    parser.add_argument("--version", action="version", version=f"vortex {VERSION}")
    return parser.parse_args(argv)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    args = parse_args()
    cfg = config.load()

    if args.output:
        cfg["download_dir"] = args.output
    if args.cookies:
        cfg["cookies_browser"] = args.cookies
    if args.no_thumbnail:
        cfg["embed_thumbnail"] = False
    if args.no_metadata:
        cfg["embed_metadata"] = False

    config.download_dir(cfg).mkdir(parents=True, exist_ok=True)

    try:
        if args.urls:
            code = cli(cfg, args)
        else:
            interactive(cfg)
            code = 0
    except KeyboardInterrupt:
        console.print(f"\n[{ui.WARN}]interrupted[/]")
        code = 130

    sys.exit(code)


if __name__ == "__main__":
    main()
