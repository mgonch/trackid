"""Tests for recognition backends (using mocked HTTP)."""

import json

import pytest
import responses as resp_mock

from trackid.recognizer import (
    ACRCloudRecognizer,
    AuddRecognizer,
    RecognitionError,
    make_recognizer,
)

SAMPLE_BYTES = b"\xff\xfb" + b"\x00" * 128   # fake MP3 header + silence


class TestAuddRecognizer:
    @resp_mock.activate
    def test_successful_match(self):
        resp_mock.add(
            resp_mock.POST,
            "https://api.audd.io/",
            json={
                "status": "success",
                "result": {
                    "artist": "Function",
                    "title": "Incubation",
                    "label": "Function",
                    "album": "The Incubation",
                    "release_date": "2012-01-01",
                },
            },
        )
        rec = AuddRecognizer(api_token="test-token")
        result = rec.recognise(SAMPLE_BYTES)

        assert result is not None
        assert result.artist == "Function"
        assert result.title == "Incubation"
        assert result.label == "Function"

    @resp_mock.activate
    def test_no_match_returns_none(self):
        resp_mock.add(
            resp_mock.POST,
            "https://api.audd.io/",
            json={"status": "success", "result": None},
        )
        rec = AuddRecognizer()
        assert rec.recognise(SAMPLE_BYTES) is None

    @resp_mock.activate
    def test_api_error_status_raises(self):
        resp_mock.add(
            resp_mock.POST,
            "https://api.audd.io/",
            json={"status": "error", "error": {"error_code": 900, "error_message": "Monthly limit exceeded"}},
        )
        rec = AuddRecognizer()
        with pytest.raises(RecognitionError, match="Monthly limit exceeded"):
            rec.recognise(SAMPLE_BYTES)

    @resp_mock.activate
    def test_http_error_raises(self):
        resp_mock.add(
            resp_mock.POST,
            "https://api.audd.io/",
            status=500,
            body="Internal Server Error",
        )
        rec = AuddRecognizer()
        with pytest.raises(RecognitionError):
            rec.recognise(SAMPLE_BYTES)

    @resp_mock.activate
    def test_network_failure_raises(self):
        resp_mock.add(
            resp_mock.POST,
            "https://api.audd.io/",
            body=ConnectionError("network error"),
        )
        rec = AuddRecognizer()
        with pytest.raises(RecognitionError):
            rec.recognise(SAMPLE_BYTES)


class TestACRCloudRecognizer:
    @resp_mock.activate
    def test_successful_match(self):
        resp_mock.add(
            resp_mock.POST,
            "https://identify-eu-west-1.acrcloud.com/v1/identify",
            json={
                "status": {"code": 0, "msg": "Success"},
                "metadata": {
                    "music": [
                        {
                            "title": "Black Sun",
                            "artists": [{"name": "Surgeon"}],
                            "label": "Dynamic Tension",
                            "album": {"name": "Force + Form"},
                            "release_date": "1999-01-01",
                        }
                    ]
                },
            },
        )
        rec = ACRCloudRecognizer("key", "secret")
        result = rec.recognise(SAMPLE_BYTES)

        assert result is not None
        assert result.title == "Black Sun"
        assert result.artist == "Surgeon"

    @resp_mock.activate
    def test_no_music_returns_none(self):
        resp_mock.add(
            resp_mock.POST,
            "https://identify-eu-west-1.acrcloud.com/v1/identify",
            json={"status": {"code": 1001, "msg": "No result"}, "metadata": {}},
        )
        rec = ACRCloudRecognizer("key", "secret")
        assert rec.recognise(SAMPLE_BYTES) is None

    @resp_mock.activate
    def test_api_error_raises(self):
        resp_mock.add(
            resp_mock.POST,
            "https://identify-eu-west-1.acrcloud.com/v1/identify",
            json={"status": {"code": 3000, "msg": "Recognize failed"}, "metadata": {}},
        )
        rec = ACRCloudRecognizer("key", "secret")
        with pytest.raises(RecognitionError, match="Recognize failed"):
            rec.recognise(SAMPLE_BYTES)


class TestMakeRecognizer:
    def test_audd_default(self):
        rec = make_recognizer("audd")
        assert isinstance(rec, AuddRecognizer)

    def test_acrcloud(self):
        rec = make_recognizer("acrcloud", acr_key="k", acr_secret="s")
        assert isinstance(rec, ACRCloudRecognizer)

    def test_acrcloud_missing_creds_raises(self):
        with pytest.raises(ValueError):
            make_recognizer("acrcloud")

    def test_unknown_backend_raises(self):
        with pytest.raises(ValueError):
            make_recognizer("shazam")
