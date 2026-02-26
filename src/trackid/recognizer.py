"""Audio recognition backends.

Supported backends
------------------
audd   – https://audd.io  (free tier: 300 req/month, no key required for testing)
acrcloud – https://acrcloud.com  (free tier: 1 000 req/day)

Both are queried via HTTP; the caller chooses the backend through the
``Recognizer`` factory.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import time
from dataclasses import dataclass, field
from typing import Any

import requests


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class RecognitionResult:
    """Normalised result from any recognition backend."""

    title: str
    artist: str
    label: str = ""
    album: str = ""
    release_date: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def __str__(self) -> str:
        parts = [self.artist, self.title]
        if self.label:
            parts.append(f"[{self.label}]")
        return " – ".join(parts)


# ---------------------------------------------------------------------------
# AudD backend
# ---------------------------------------------------------------------------

AUDD_ENDPOINT = "https://api.audd.io/"


class AuddRecognizer:
    """Recognise audio using the AudD REST API.

    Parameters
    ----------
    api_token:
        AudD API token.  If *None* a token-less request is sent, which works
        for the free sandbox but has very strict rate limits.
    """

    def __init__(self, api_token: str | None = None) -> None:
        self.api_token = api_token
        self._session = requests.Session()

    def recognise(self, mp3_bytes: bytes, timeout: int = 20) -> RecognitionResult | None:
        """Return the best match for *mp3_bytes* or *None* if nothing matched."""
        data: dict[str, Any] = {
            "return": "apple_music,spotify",
        }
        if self.api_token:
            data["api_token"] = self.api_token

        files = {"file": ("sample.mp3", io.BytesIO(mp3_bytes), "audio/mpeg")}

        try:
            resp = self._session.post(
                AUDD_ENDPOINT, data=data, files=files, timeout=timeout
            )
            resp.raise_for_status()
        except (requests.RequestException, OSError) as exc:
            raise RecognitionError(f"AudD request failed: {exc}") from exc

        payload = resp.json()
        if payload.get("status") != "success":
            error = payload.get("error", {})
            msg = error.get("error_message") or f"code {error.get('error_code', '?')}"
            raise RecognitionError(f"AudD API error: {msg}")

        result = payload.get("result")
        if not result:
            return None

        return RecognitionResult(
            title=result.get("title", ""),
            artist=result.get("artist", ""),
            label=result.get("label", ""),
            album=result.get("album", ""),
            release_date=result.get("release_date", ""),
            raw=result,
        )


# ---------------------------------------------------------------------------
# ACRCloud backend
# ---------------------------------------------------------------------------

ACRCLOUD_ENDPOINT = "https://identify-eu-west-1.acrcloud.com/v1/identify"


class ACRCloudRecognizer:
    """Recognise audio using the ACRCloud REST API.

    Parameters
    ----------
    access_key / access_secret:
        Credentials from your ACRCloud project console.
    host:
        ACRCloud region endpoint (default: EU West).
    """

    def __init__(
        self,
        access_key: str,
        access_secret: str,
        host: str = "identify-eu-west-1.acrcloud.com",
    ) -> None:
        self.access_key = access_key
        self.access_secret = access_secret.encode()
        self.host = host
        self._session = requests.Session()

    def recognise(self, mp3_bytes: bytes, timeout: int = 20) -> RecognitionResult | None:
        timestamp = str(int(time.time()))
        string_to_sign = "\n".join(
            ["POST", "/v1/identify", self.access_key, "audio", "1", timestamp]
        )
        signature = base64.b64encode(
            hmac.new(self.access_secret, string_to_sign.encode(), hashlib.sha1).digest()
        ).decode()

        data = {
            "access_key": self.access_key,
            "sample_bytes": str(len(mp3_bytes)),
            "timestamp": timestamp,
            "signature": signature,
            "data_type": "audio",
            "signature_version": "1",
        }
        files = {"sample": ("sample.mp3", io.BytesIO(mp3_bytes), "audio/mpeg")}

        try:
            resp = self._session.post(
                f"https://{self.host}/v1/identify",
                data=data,
                files=files,
                timeout=timeout,
            )
            resp.raise_for_status()
        except (requests.RequestException, OSError) as exc:
            raise RecognitionError(f"ACRCloud request failed: {exc}") from exc

        payload = resp.json()
        status = payload.get("status", {})
        code = status.get("code")
        if code != 0:
            if code == 1001:  # "No result" is a normal no-match, not an error
                return None
            raise RecognitionError(f"ACRCloud API error: {status.get('msg', code)}")

        metadata = payload.get("metadata", {})
        music_list = metadata.get("music", [])
        if not music_list:
            return None

        track = music_list[0]
        artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
        label = ""
        if track.get("label"):
            label = track["label"]
        elif track.get("external_metadata", {}).get("beatport", {}).get("track", {}):
            bp = track["external_metadata"]["beatport"]["track"]
            label = bp.get("label", {}).get("name", "")

        return RecognitionResult(
            title=track.get("title", ""),
            artist=artists,
            label=label,
            album=track.get("album", {}).get("name", ""),
            release_date=track.get("release_date", ""),
            raw=track,
        )


# ---------------------------------------------------------------------------
# Errors & factory
# ---------------------------------------------------------------------------

class RecognitionError(Exception):
    pass


def make_recognizer(
    backend: str = "audd",
    *,
    audd_token: str | None = None,
    acr_key: str | None = None,
    acr_secret: str | None = None,
    acr_host: str = "identify-eu-west-1.acrcloud.com",
) -> AuddRecognizer | ACRCloudRecognizer:
    """Return a configured recognizer instance for the chosen *backend*."""
    if backend == "audd":
        return AuddRecognizer(api_token=audd_token)
    if backend == "acrcloud":
        if not acr_key or not acr_secret:
            raise ValueError("ACRCloud requires --acr-key and --acr-secret.")
        return ACRCloudRecognizer(
            access_key=acr_key, access_secret=acr_secret, host=acr_host
        )
    raise ValueError(f"Unknown backend: {backend!r}. Choose 'audd' or 'acrcloud'.")
