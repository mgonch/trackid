"""trackid – identify tracks inside a DJ set.

Usage examples
--------------
# Identify tracks from a SoundCloud set (AudD, no key needed for testing)
trackid identify https://soundcloud.com/dj/mix-title

# Use your AudD API token for higher rate limits
trackid identify https://soundcloud.com/dj/mix-title --audd-token YOUR_TOKEN

# Use ACRCloud backend (better DJ-mix detection)
trackid identify https://soundcloud.com/dj/mix-title \\
    --backend acrcloud --acr-key KEY --acr-secret SECRET

# Identify a local file, sample every 20 s
trackid identify /path/to/set.wav --step 20

# Save results to a text file
trackid identify https://... --output tracklist.txt

# Launch the web GUI (opens browser automatically)
trackid serve

# Custom host/port
trackid serve --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import click
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from .downloader import DownloadError, download_audio
from .recognizer import RecognitionError, make_recognizer
from .sampler import chunk_to_mp3_bytes, iter_chunks
from .tracklist import TrackEntry, build_tracklist, format_tracklist

console = Console(stderr=True)   # progress/status → stderr
out_console = Console()          # final result → stdout


# ---------------------------------------------------------------------------
# CLI root
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(package_name="trackid")
def main() -> None:
    """Identify tracks inside DJ sets (SoundCloud, Mixcloud, YouTube, local files)."""


# ---------------------------------------------------------------------------
# identify command
# ---------------------------------------------------------------------------

@main.command()
@click.argument("source")
@click.option(
    "--backend",
    type=click.Choice(["audd", "acrcloud"]),
    default="acrcloud",
    show_default=True,
    help="Audio recognition backend.",
)
@click.option("--audd-token", envvar="AUDD_TOKEN", default=None, help="AudD API token.")
@click.option("--acr-key", envvar="ACR_KEY", default=None, help="ACRCloud access key.")
@click.option(
    "--acr-secret", envvar="ACR_SECRET", default=None, help="ACRCloud access secret."
)
@click.option(
    "--acr-host",
    envvar="ACR_HOST",
    default="identify-us-west-2.acrcloud.com",
    show_default=True,
    help="ACRCloud region host.",
)
@click.option(
    "--step",
    default=30,
    show_default=True,
    type=int,
    help="Seconds between consecutive samples.",
)
@click.option(
    "--chunk",
    default=12,
    show_default=True,
    type=int,
    help="Length of each audio sample sent to the API (seconds).",
)
@click.option(
    "--min-hits",
    default=1,
    show_default=True,
    type=int,
    help=(
        "Minimum API hits for a track to appear in the tracklist. "
        "Raise to 2–3 to reduce false positives."
    ),
)
@click.option(
    "--output",
    "-o",
    default=None,
    type=click.Path(dir_okay=False, writable=True),
    help="Save tracklist to this file (plain text).",
)
@click.option(
    "--delay",
    default=0.5,
    show_default=True,
    type=float,
    help="Seconds to wait between API requests (rate-limit friendly).",
)
def identify(
    source: str,
    backend: str,
    audd_token: str | None,
    acr_key: str | None,
    acr_secret: str | None,
    acr_host: str,
    step: int,
    chunk: int,
    min_hits: int,
    output: str | None,
    delay: float,
) -> None:
    """Identify all tracks in SOURCE (URL or local file path)."""

    # ── 1. Resolve audio file ────────────────────────────────────────────────
    source_path = Path(source)
    tmp_dir: str | None = None

    if source_path.exists() and source_path.is_file():
        audio_file = source_path
        console.print(f"[bold green]✓[/] Using local file: [cyan]{audio_file}[/]")
    else:
        tmp_dir = tempfile.mkdtemp(prefix="trackid_")
        console.print(f"[bold blue]↓[/] Downloading audio from [cyan]{source}[/] …")
        try:
            audio_file = download_audio(source, dest_dir=tmp_dir)
        except DownloadError as exc:
            console.print(f"[bold red]✗ Download failed:[/] {exc}")
            sys.exit(1)
        console.print(f"[bold green]✓[/] Downloaded: [cyan]{audio_file.name}[/]")

    # ── 2. Build recognizer ──────────────────────────────────────────────────
    try:
        recognizer = make_recognizer(
            backend,
            audd_token=audd_token,
            acr_key=acr_key,
            acr_secret=acr_secret,
            acr_host=acr_host,
        )
    except ValueError as exc:
        console.print(f"[bold red]✗ Configuration error:[/] {exc}")
        sys.exit(1)

    # ── 3. Slice & recognise ─────────────────────────────────────────────────
    chunks = list(iter_chunks(audio_file, chunk_duration=chunk, step=step))
    if not chunks:
        console.print("[bold red]✗[/] No audio chunks could be extracted.")
        sys.exit(1)

    detections: list[tuple[float, object]] = []
    identified_count = 0

    console.print(
        f"[bold blue]🔍[/] Sampling {len(chunks)} positions "
        f"(every {step}s, {chunk}s chunks) via [bold]{backend}[/] …\n"
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Identifying …", total=len(chunks))

        for ch in chunks:
            ts = _fmt_time(ch.offset_seconds)
            progress.update(task, description=f"[dim]{ts}[/dim] Identifying …")

            try:
                mp3_bytes = chunk_to_mp3_bytes(ch)
                result = recognizer.recognise(mp3_bytes)
            except RecognitionError as exc:
                console.print(f"[yellow]⚠ {ts}: {exc}[/]")
                result = None

            detections.append((ch.offset_seconds, result))
            if result:
                identified_count += 1
                progress.update(
                    task,
                    description=(
                        f"[dim]{ts}[/dim] [green]✓[/] {result.artist} – {result.title}"
                    ),
                )

            progress.advance(task)
            if delay > 0:
                time.sleep(delay)

    console.print(
        f"\n[bold green]✓[/] {identified_count}/{len(chunks)} samples matched.\n"
    )

    # ── 4. Build & display tracklist ─────────────────────────────────────────
    tracklist = build_tracklist(detections, min_hits=min_hits)
    _print_rich_table(tracklist)

    plaintext = format_tracklist(tracklist)
    if output:
        Path(output).write_text(plaintext, encoding="utf-8")
        console.print(f"\n[bold green]✓[/] Saved to [cyan]{output}[/]")
    else:
        out_console.print(plaintext)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_time(seconds: float) -> str:
    s = int(seconds)
    h, remainder = divmod(s, 3600)
    m, sec = divmod(remainder, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def _print_rich_table(tracklist: list[TrackEntry]) -> None:
    if not tracklist:
        console.print("[yellow]No tracks identified.[/]")
        return

    table = Table(title="Identified Tracklist", show_lines=True)
    table.add_column("#", style="bold cyan", justify="right", no_wrap=True)
    table.add_column("Time", style="dim", no_wrap=True)
    table.add_column("Artist", style="bold")
    table.add_column("Title")
    table.add_column("Label", style="dim")

    for entry in tracklist:
        table.add_row(
            str(entry.number),
            entry.timestamp,
            entry.artist,
            entry.title,
            entry.label,
        )

    console.print(table)


# ---------------------------------------------------------------------------
# serve command
# ---------------------------------------------------------------------------

@main.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host.")
@click.option("--port", default=7842, show_default=True, type=int, help="Bind port.")
@click.option(
    "--no-browser", is_flag=True, default=False, help="Don't open a browser tab."
)
def serve(host: str, port: int, no_browser: bool) -> None:
    """Launch the web GUI and (optionally) open it in a browser.

    \b
    Requires: pip install "trackid[gui]"
    """
    try:
        import uvicorn
    except ImportError:
        console.print(
            "[bold red]✗[/] uvicorn is not installed.\n"
            "Run: [cyan]pip install 'trackid[gui]'[/]"
        )
        raise SystemExit(1)

    url = f"http://{host}:{port}"
    console.print(f"[bold green]✓[/] trackid GUI running at [cyan]{url}[/]")
    console.print("  Press [bold]Ctrl+C[/] to stop.\n")

    if not no_browser:
        import threading, webbrowser
        # Open the browser after a short delay so uvicorn is ready
        threading.Timer(1.2, webbrowser.open, args=(url,)).start()

    from .web import app as fastapi_app
    uvicorn.run(fastapi_app, host=host, port=port, log_level="warning")
