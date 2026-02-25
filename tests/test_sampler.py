"""Tests for the audio sampler (uses synthetic pydub audio)."""

import shutil

import pytest
from pydub.generators import Sine

from trackid.sampler import AudioChunk, chunk_to_mp3_bytes, iter_chunks

ffmpeg_required = pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="ffmpeg not installed",
)


def _make_wav(duration_seconds: int = 120, sample_rate: int = 22050) -> str:
    """Write a synthetic sine-wave WAV to a temp file and return its path."""
    import tempfile

    tone = Sine(440).to_audio_segment(duration=duration_seconds * 1000)
    tone = tone.set_frame_rate(sample_rate).set_channels(1)

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tone.export(tmp.name, format="wav")
    return tmp.name


class TestIterChunks:
    def test_number_of_chunks(self):
        path = _make_wav(120)
        chunks = list(iter_chunks(path, chunk_duration=12, step=30))
        # 120 s / 30 s = 4 steps: offsets 0, 30, 60, 90
        assert len(chunks) == 4

    def test_chunk_type(self):
        path = _make_wav(60)
        chunks = list(iter_chunks(path, chunk_duration=12, step=30))
        assert all(isinstance(c, AudioChunk) for c in chunks)

    def test_offset_increments(self):
        path = _make_wav(90)
        chunks = list(iter_chunks(path, chunk_duration=12, step=30))
        offsets = [c.offset_seconds for c in chunks]
        assert offsets == [0.0, 30.0, 60.0]

    def test_chunk_duration_capped_at_audio_end(self):
        # 5-second audio, 12-second chunk → single chunk of ~5 s
        path = _make_wav(5)
        chunks = list(iter_chunks(path, chunk_duration=12, step=30))
        assert len(chunks) == 1
        assert 4.5 <= chunks[0].duration_seconds <= 5.1

    def test_very_short_trailing_chunk_skipped(self):
        # 31-second audio, step 30 → first chunk at 0, 1-second trailing chunk skipped
        path = _make_wav(31)
        chunks = list(iter_chunks(path, chunk_duration=12, step=30))
        offsets = [c.offset_seconds for c in chunks]
        assert 30.0 not in offsets or chunks[-1].duration_seconds >= 5.0


class TestChunkToMp3Bytes:
    @ffmpeg_required
    def test_returns_bytes(self):
        path = _make_wav(10)
        chunks = list(iter_chunks(path, chunk_duration=10, step=30))
        assert len(chunks) >= 1
        data = chunk_to_mp3_bytes(chunks[0])
        assert isinstance(data, bytes)
        assert len(data) > 0

    @ffmpeg_required
    def test_mp3_header(self):
        path = _make_wav(10)
        chunks = list(iter_chunks(path, chunk_duration=10, step=30))
        data = chunk_to_mp3_bytes(chunks[0])
        # MP3 files start with 0xFF 0xFB (sync word) or ID3 tag 0x49 0x44 0x33
        assert data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2") or data[:3] == b"ID3"
