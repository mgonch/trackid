"""Download audio from a URL (SoundCloud, YouTube, Mixcloud, …) using yt-dlp."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


class DownloadError(Exception):
    pass


def download_audio(url: str, dest_dir: str | Path | None = None) -> Path:
    """Download audio from *url* and return the path to the resulting file.

    Parameters
    ----------
    url:
        Any URL supported by yt-dlp (SoundCloud, YouTube, Mixcloud, …).
    dest_dir:
        Directory where the file will be saved.  A temporary directory is
        created when this is *None*.

    Returns
    -------
    Path
        Absolute path to the downloaded audio file (always WAV for
        downstream processing consistency).
    """
    if dest_dir is None:
        dest_dir = Path(tempfile.mkdtemp(prefix="trackid_"))
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    output_template = str(dest_dir / "%(title)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--extract-audio",
        "--audio-format", "wav",
        "--audio-quality", "0",
        "--output", output_template,
        "--no-progress",
        "--quiet",
        url,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise DownloadError(
            f"yt-dlp failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )

    wav_files = list(dest_dir.glob("*.wav"))
    if not wav_files:
        raise DownloadError(
            "yt-dlp did not produce a WAV file in the expected directory."
        )

    # Return the most-recently-modified file in case multiple tracks are present
    wav_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return wav_files[0]
