"""Slice an audio file into overlapping fingerprint-sized chunks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from pydub import AudioSegment


@dataclass(frozen=True)
class AudioChunk:
    """A short audio excerpt and its position in the source recording."""

    offset_seconds: float      # start of this chunk relative to the full set
    duration_seconds: float    # length of the chunk
    audio: AudioSegment        # raw audio data


def iter_chunks(
    audio_path: str | Path,
    chunk_duration: int = 12,
    step: int = 30,
) -> Iterator[AudioChunk]:
    """Yield overlapping chunks from an audio file.

    Parameters
    ----------
    audio_path:
        Path to a WAV (or any pydub-readable) file.
    chunk_duration:
        Length of each sample sent to the recognition API, in seconds.
        12 s gives enough content for Shazam-style fingerprinting while
        staying within most API free-tier payload limits.
    step:
        How many seconds to advance between consecutive chunks.
        30 s means we sample every half-minute; reduce for higher recall.

    Yields
    ------
    AudioChunk
        Successive chunks until the end of the recording.
    """
    audio = AudioSegment.from_file(str(audio_path))
    total_ms = len(audio)
    chunk_ms = chunk_duration * 1000
    step_ms = step * 1000

    offset_ms = 0
    while offset_ms < total_ms:
        end_ms = min(offset_ms + chunk_ms, total_ms)
        segment = audio[offset_ms:end_ms]
        # Skip very short trailing segments that cannot be fingerprinted reliably
        if len(segment) >= 5_000:
            yield AudioChunk(
                offset_seconds=offset_ms / 1000,
                duration_seconds=len(segment) / 1000,
                audio=segment,
            )
        offset_ms += step_ms


def chunk_to_mp3_bytes(chunk: AudioChunk, bitrate: str = "128k") -> bytes:
    """Export a chunk as MP3 bytes suitable for uploading to a recognition API."""
    import io

    buf = io.BytesIO()
    chunk.audio.export(buf, format="mp3", bitrate=bitrate)
    return buf.getvalue()
