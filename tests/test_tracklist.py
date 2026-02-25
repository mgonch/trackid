"""Tests for tracklist deduplication and formatting."""

from trackid.recognizer import RecognitionResult
from trackid.tracklist import TrackEntry, build_tracklist, format_tracklist, _fmt_time


def _result(artist: str, title: str, label: str = "") -> RecognitionResult:
    return RecognitionResult(artist=artist, title=title, label=label)


class TestFmtTime:
    def test_under_one_hour(self):
        assert _fmt_time(90) == "01:30"

    def test_over_one_hour(self):
        assert _fmt_time(3661) == "1:01:01"

    def test_zero(self):
        assert _fmt_time(0) == "00:00"


class TestBuildTracklist:
    def test_empty_detections(self):
        assert build_tracklist([]) == []

    def test_none_only(self):
        assert build_tracklist([(0.0, None), (30.0, None)]) == []

    def test_single_track_single_hit(self):
        detections = [(0.0, _result("Surgeon", "Breaking the Frame"))]
        entries = build_tracklist(detections, min_hits=1)
        assert len(entries) == 1
        e = entries[0]
        assert e.artist == "Surgeon"
        assert e.title == "Breaking the Frame"
        assert e.first_seen_at == 0.0
        assert e.number == 1

    def test_deduplicates_consecutive_hits(self):
        r = _result("Perc", "Power Struggle")
        detections = [(0.0, r), (30.0, r), (60.0, r)]
        entries = build_tracklist(detections, min_hits=1)
        assert len(entries) == 1
        assert entries[0].hit_count == 3
        assert entries[0].last_seen_at == 60.0

    def test_min_hits_filters_low_confidence(self):
        r = _result("Low Confidence Track", "Blip")
        detections = [(0.0, r)]
        entries = build_tracklist(detections, min_hits=2)
        assert entries == []

    def test_multiple_tracks_ordered_by_time(self):
        r1 = _result("Phase Fatale", "Hypnosis")
        r2 = _result("Blawan", "Getting Me Down")
        r3 = _result("Shackleton", "Blood on My Hands")
        detections = [
            (0.0, r1), (30.0, r1),
            (120.0, r2), (150.0, r2),
            (300.0, r3),
        ]
        entries = build_tracklist(detections, min_hits=1)
        assert len(entries) == 3
        assert entries[0].artist == "Phase Fatale"
        assert entries[1].artist == "Blawan"
        assert entries[2].artist == "Shackleton"
        assert [e.number for e in entries] == [1, 2, 3]

    def test_mixed_none_and_results(self):
        r = _result("Regis", "Penetration")
        detections = [(0.0, None), (30.0, r), (60.0, None), (90.0, r)]
        entries = build_tracklist(detections, min_hits=1)
        assert len(entries) == 1

    def test_case_insensitive_dedup(self):
        r1 = RecognitionResult(artist="Surgeon", title="Breaking The Frame")
        r2 = RecognitionResult(artist="surgeon", title="breaking the frame")
        detections = [(0.0, r1), (30.0, r2)]
        entries = build_tracklist(detections, min_hits=1)
        assert len(entries) == 1

    def test_label_preserved(self):
        r = _result("Headless Horseman", "Acid Pony Club", label="Tresor")
        entries = build_tracklist([(0.0, r)], min_hits=1)
        assert entries[0].label == "Tresor"


class TestFormatTracklist:
    def test_empty_returns_message(self):
        assert format_tracklist([]) == "(no tracks identified)"

    def test_single_entry(self):
        entry = TrackEntry(
            number=1,
            title="Overdrive",
            artist="Ancient Methods",
            label="Methkin",
            first_seen_at=90.0,
            last_seen_at=120.0,
        )
        output = format_tracklist([entry])
        assert "Ancient Methods" in output
        assert "Overdrive" in output
        assert "01:30" in output
        assert "Total: 1" in output
