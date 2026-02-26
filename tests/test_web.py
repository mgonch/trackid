"""Tests for the FastAPI web application."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from trackid.web import app

client = TestClient(app)


class TestIndex:
    def test_returns_html(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "trackid" in resp.text


class TestIdentifyEndpoint:
    def test_returns_job_id(self):
        with patch("trackid.web._run_job"):
            resp = client.post(
                "/api/identify",
                json={"source": "https://soundcloud.com/test/mix"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert len(data["job_id"]) == 36   # UUID format


class TestStreamEndpoint:
    def test_unknown_job_returns_404(self):
        resp = client.get("/api/stream/nonexistent-job-id")
        assert resp.status_code == 404

    def test_streams_events_for_known_job(self):
        from trackid.web import JobState, _jobs

        job_id = "test-stream-job"
        state = JobState()
        _jobs[job_id] = state
        state.push({"type": "status", "message": "hello"})
        state.finish([])

        try:
            resp = client.get(f"/api/stream/{job_id}")
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            # Response body should contain SSE data lines
            assert "data:" in resp.text
        finally:
            _jobs.pop(job_id, None)


class TestResultEndpoint:
    def test_unknown_job_returns_404(self):
        resp = client.get("/api/result/no-such-job")
        assert resp.status_code == 404

    def test_running_job_returns_202(self):
        from trackid.web import JobState, _jobs

        job_id = "test-running-job"
        _jobs[job_id] = JobState()   # not done yet
        try:
            resp = client.get(f"/api/result/{job_id}")
            assert resp.status_code == 202
        finally:
            _jobs.pop(job_id, None)

    def test_completed_job_returns_tracklist(self):
        from trackid.web import JobState, _jobs

        job_id = "test-done-job"
        state = JobState()
        state.finish([{"number": 1, "artist": "Surgeon", "title": "Black Sun",
                       "label": "DT", "timestamp": "00:00", "hit_count": 2}])
        _jobs[job_id] = state
        try:
            resp = client.get(f"/api/result/{job_id}")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["tracklist"]) == 1
            assert data["tracklist"][0]["artist"] == "Surgeon"
        finally:
            _jobs.pop(job_id, None)


class TestDeleteEndpoint:
    def test_delete_existing_job(self):
        from trackid.web import JobState, _jobs

        job_id = "test-delete-job"
        _jobs[job_id] = JobState()
        resp = client.delete(f"/api/job/{job_id}")
        assert resp.status_code == 200
        assert job_id not in _jobs

    def test_delete_nonexistent_job(self):
        resp = client.delete("/api/job/no-such-job")
        assert resp.status_code == 404


class TestUploadEndpoint:
    def test_upload_wav_file(self, tmp_path):
        # Create a minimal WAV stub (44-byte header is enough for the test)
        wav_data = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + \
                   (16).to_bytes(4, "little") + b"\x01\x00\x01\x00" + \
                   (22050).to_bytes(4, "little") + (44100).to_bytes(4, "little") + \
                   b"\x02\x00\x10\x00data" + (0).to_bytes(4, "little")

        resp = client.post(
            "/api/upload",
            files={"file": ("test_set.wav", wav_data, "audio/wav")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "path" in data
        assert data["filename"] == "test_set.wav"
