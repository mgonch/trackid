"""FastAPI web application for trackid.

Endpoints
---------
GET  /                        Serve the single-page frontend
POST /api/identify            Start a recognition job (returns {"job_id": "…"})
GET  /api/stream/{job_id}     Server-Sent Events: live progress updates
GET  /api/result/{job_id}     Final tracklist (JSON) once the job is done
DELETE /api/job/{job_id}      Cancel / discard a running or completed job
POST /api/upload              Accept a local file upload; returns a temp path
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .downloader import DownloadError, download_audio
from .recognizer import RecognitionError, make_recognizer
from .sampler import chunk_to_mp3_bytes, iter_chunks
from .tracklist import TrackEntry, build_tracklist

# ---------------------------------------------------------------------------
# App & static files
# ---------------------------------------------------------------------------

app = FastAPI(title="trackid", version="0.1.0")

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


# ---------------------------------------------------------------------------
# In-memory job store
# ---------------------------------------------------------------------------

_executor = ThreadPoolExecutor(max_workers=4)

class JobState:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.done = False
        self.tracklist: list[dict] = []
        self._waiters: list[asyncio.Event] = []

    def push(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        for w in self._waiters:
            w.set()

    def finish(self, tracklist: list[dict]) -> None:
        self.tracklist = tracklist
        self.done = True
        self.push({"type": "done", "tracklist": tracklist})

    def error(self, message: str) -> None:
        self.done = True
        self.push({"type": "error", "message": message})

    async def wait_for_new(self, cursor: int) -> None:
        if cursor < len(self.events):
            return
        ev = asyncio.Event()
        self._waiters.append(ev)
        try:
            await asyncio.wait_for(ev.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass
        finally:
            self._waiters.discard(ev)


_jobs: dict[str, JobState] = {}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class IdentifyRequest(BaseModel):
    source: str                          # URL or path returned by /api/upload
    backend: str = "audd"
    audd_token: str | None = None
    acr_key: str | None = None
    acr_secret: str | None = None
    acr_host: str = "identify-eu-west-1.acrcloud.com"
    step: int = 30
    chunk: int = 12
    min_hits: int = 1
    delay: float = 0.5


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def _run_job(job_id: str, req: IdentifyRequest) -> None:
    """Blocking worker executed in a thread-pool thread."""
    state = _jobs[job_id]

    # -- 1. Download or resolve file ----------------------------------------
    tmp_dir: str | None = None
    source_path = Path(req.source)

    if source_path.exists() and source_path.is_file():
        audio_file = source_path
        state.push({"type": "status", "message": f"Using uploaded file: {audio_file.name}"})
    else:
        tmp_dir = tempfile.mkdtemp(prefix="trackid_")
        state.push({"type": "status", "message": "Downloading audio…"})
        try:
            audio_file = download_audio(req.source, dest_dir=tmp_dir)
        except DownloadError as exc:
            state.error(f"Download failed: {exc}")
            return
        state.push({"type": "status", "message": f"Downloaded: {audio_file.name}"})

    # -- 2. Slice into chunks -----------------------------------------------
    chunks = list(iter_chunks(audio_file, chunk_duration=req.chunk, step=req.step))
    if not chunks:
        state.error("No audio chunks could be extracted.")
        return

    state.push({"type": "total", "total": len(chunks)})

    # -- 3. Recognise each chunk --------------------------------------------
    try:
        recognizer = make_recognizer(
            req.backend,
            audd_token=req.audd_token,
            acr_key=req.acr_key,
            acr_secret=req.acr_secret,
            acr_host=req.acr_host,
        )
    except ValueError as exc:
        state.error(str(exc))
        return

    detections: list[tuple[float, Any]] = []
    for i, ch in enumerate(chunks):
        if state.done:   # cancelled externally
            return

        ts = _fmt_time(ch.offset_seconds)
        try:
            mp3_bytes = chunk_to_mp3_bytes(ch)
            result = recognizer.recognise(mp3_bytes)
        except RecognitionError as exc:
            result = None
            state.push({"type": "warn", "offset": ch.offset_seconds, "message": str(exc)})

        detections.append((ch.offset_seconds, result))

        event: dict[str, Any] = {
            "type": "sample",
            "index": i,
            "offset": ch.offset_seconds,
            "timestamp": ts,
        }
        if result:
            event["match"] = {
                "artist": result.artist,
                "title": result.title,
                "label": result.label,
            }
        state.push(event)

        if req.delay > 0:
            time.sleep(req.delay)

    # -- 4. Build tracklist --------------------------------------------------
    tracklist = build_tracklist(detections, min_hits=req.min_hits)
    state.finish([
        {
            "number": e.number,
            "timestamp": e.timestamp,
            "artist": e.artist,
            "title": e.title,
            "label": e.label,
            "hit_count": e.hit_count,
        }
        for e in tracklist
    ])


def _fmt_time(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.post("/api/identify")
async def start_identify(req: IdentifyRequest) -> dict:
    job_id = str(uuid.uuid4())
    _jobs[job_id] = JobState()
    loop = asyncio.get_event_loop()
    loop.run_in_executor(_executor, _run_job, job_id, req)
    return {"job_id": job_id}


@app.get("/api/stream/{job_id}")
async def stream_job(job_id: str) -> StreamingResponse:
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator() -> AsyncIterator[str]:
        state = _jobs[job_id]
        cursor = 0
        while True:
            while cursor < len(state.events):
                ev = state.events[cursor]
                yield f"data: {json.dumps(ev)}\n\n"
                cursor += 1
                if ev.get("type") in ("done", "error"):
                    return
            if state.done and cursor >= len(state.events):
                return
            await state.wait_for_new(cursor)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/result/{job_id}")
async def get_result(job_id: str) -> dict:
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    state = _jobs[job_id]
    if not state.done:
        raise HTTPException(status_code=202, detail="Job still running")
    return {"tracklist": state.tracklist}


@app.delete("/api/job/{job_id}")
async def delete_job(job_id: str) -> dict:
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    state = _jobs.pop(job_id)
    state.done = True   # signal any running worker to stop
    return {"status": "deleted"}


@app.post("/api/upload")
async def upload_file(file: UploadFile) -> dict:
    """Accept an audio file upload and return a server-side temp path."""
    tmp = tempfile.NamedTemporaryFile(
        suffix=Path(file.filename or "upload.wav").suffix,
        delete=False,
        prefix="trackid_upload_",
    )
    content = await file.read()
    tmp.write(content)
    tmp.close()
    return {"path": tmp.name, "filename": file.filename}
