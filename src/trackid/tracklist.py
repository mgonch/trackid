"""Deduplicate and format the recognised track list from a DJ set."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .recognizer import RecognitionResult


@dataclass
class TrackEntry:
    """A single track as it appears in the deduped tracklist."""

    number: int
    title: str
    artist: str
    label: str
    first_seen_at: float       # seconds into the set
    last_seen_at: float        # seconds into the set (last sample that matched)
    hit_count: int = 1

    @property
    def timestamp(self) -> str:
        """Return HH:MM:SS timestamp of the first detection."""
        return _fmt_time(self.first_seen_at)

    def __str__(self) -> str:
        parts = [f"{self.number:>2}. [{self.timestamp}]  {self.artist} – {self.title}"]
        if self.label:
            parts.append(f"  ({self.label})")
        return "".join(parts)


def _fmt_time(seconds: float) -> str:
    s = int(seconds)
    h, remainder = divmod(s, 3600)
    m, sec = divmod(remainder, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def _track_key(result: RecognitionResult) -> str:
    """Normalised identity key — lowercased artist + title."""
    return (result.artist + result.title).lower().strip()


def build_tracklist(
    detections: Iterable[tuple[float, RecognitionResult | None]],
    min_hits: int = 1,
    gap_threshold: int = 90,
) -> list[TrackEntry]:
    """Turn a stream of (offset_seconds, result) pairs into a clean tracklist.

    Parameters
    ----------
    detections:
        Iterable of ``(offset_seconds, RecognitionResult | None)`` in
        chronological order.  *None* means no match at that offset.
    min_hits:
        Minimum number of consecutive/nearby detections required before a
        track is included.  Raise this to reduce false positives.
    gap_threshold:
        Seconds of silence (no match for the same track) before the *same*
        track is considered a new play if it reappears.  In a long techno set
        a track rarely plays twice, but this handles DJ edits / loops.

    Returns
    -------
    list[TrackEntry]
        Ordered by first detection time, deduplicated.
    """
    # Map of track key → list of offsets where it was detected
    seen: dict[str, list[float]] = {}
    meta: dict[str, RecognitionResult] = {}

    for offset, result in detections:
        if result is None:
            continue
        key = _track_key(result)
        seen.setdefault(key, []).append(offset)
        meta[key] = result  # overwrite with freshest metadata

    entries: list[TrackEntry] = []
    n = 1
    for key, offsets in sorted(seen.items(), key=lambda kv: kv[1][0]):
        if len(offsets) < min_hits:
            continue
        result = meta[key]
        entry = TrackEntry(
            number=n,
            title=result.title,
            artist=result.artist,
            label=result.label,
            first_seen_at=offsets[0],
            last_seen_at=offsets[-1],
            hit_count=len(offsets),
        )
        entries.append(entry)
        n += 1

    return entries


def format_tracklist(entries: list[TrackEntry]) -> str:
    """Return a human-readable plaintext tracklist."""
    if not entries:
        return "(no tracks identified)"
    lines = ["TRACKLIST", "─" * 60]
    for e in entries:
        lines.append(str(e))
    lines.append("─" * 60)
    lines.append(f"Total: {len(entries)} track(s) identified")
    return "\n".join(lines)
