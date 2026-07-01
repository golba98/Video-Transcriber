from __future__ import annotations

import logging
from threading import Thread
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .exports import write_exports
from .jobs import complete_job, create_job, fail_job, get_job, job_progress, update_job
from .transcriber import SUPPORTED_MODELS, default_runtime, transcribe_media
from .utils import (
    command_exists,
    ensure_directories,
    format_duration,
    probe_duration_seconds,
    remove_file,
    require_media_tools,
    safe_output_name,
    save_upload,
    validate_upload,
)

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

ensure_directories(UPLOAD_DIR, OUTPUT_DIR)

app = FastAPI(title="Video Transcriber")


@app.get("/api/health")
def health() -> dict:
    runtime = default_runtime()
    return {
        "status": "ok",
        "ffmpeg_available": command_exists("ffmpeg"),
        "ffprobe_available": command_exists("ffprobe"),
        **runtime,
    }


@app.post("/api/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    model: str = Form("small"),
    language: str = Form("auto"),
    output_format: str = Form("plain"),
) -> dict:
    if model not in SUPPORTED_MODELS:
        raise HTTPException(status_code=400, detail="Unsupported model selection.")
    if output_format not in {"plain", "timestamped", "srt"}:
        raise HTTPException(status_code=400, detail="Unsupported output format.")

    require_media_tools()
    extension = validate_upload(file)
    uploaded_path: Path | None = None

    try:
        uploaded_path = await save_upload(file, UPLOAD_DIR, extension)
        duration_seconds = probe_duration_seconds(uploaded_path)
        job = create_job(file.filename or uploaded_path.name, output_format, duration_seconds)
        worker_path = uploaded_path
        uploaded_path = None
        Thread(
            target=run_transcription_job,
            args=(job.id, worker_path, file.filename or worker_path.name, model, language, output_format, duration_seconds),
            daemon=True,
        ).start()
        return {
            "job_id": job.id,
            "status": job.status,
            "stage": job.stage,
            "duration_seconds": duration_seconds,
            "duration": format_duration(duration_seconds),
            "progress_url": f"/api/progress/{job.id}",
            "result_url": f"/api/result/{job.id}",
        }
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected transcription error")
        raise HTTPException(status_code=500, detail="Something went wrong while transcribing this file.") from exc
    finally:
        remove_file(uploaded_path)
        await file.close()


def run_transcription_job(
    job_id: str,
    uploaded_path: Path,
    source_filename: str,
    model: str,
    language: str,
    output_format: str,
    duration_seconds: float | None,
) -> None:
    def on_progress(stage: str, processed_seconds: float | None, message: str) -> None:
        total = duration_seconds or 0.0
        processed = processed_seconds or 0.0
        if total:
            message_text = f"Transcribing {format_duration(processed)} / {format_duration(total)}"
        else:
            message_text = message
        update_job(
            job_id,
            stage=stage,
            status="running",
            processed_seconds=processed,
            message=message_text,
        )

    try:
        update_job(job_id, stage="loading_model", message="Loading model")
        result = transcribe_media(uploaded_path, model, language, output_format, on_progress)
        update_job(
            job_id,
            stage="writing_files",
            message="Writing files",
            processed_seconds=duration_seconds or 0.0,
        )
        files = write_exports(result["segments"], OUTPUT_DIR, source_filename)
        download_urls = {key: f"/api/download/{filename}" for key, filename in files.items()}
        file_urls = {
            "txt": download_urls["plain"],
            "timestamped": download_urls["timestamped"],
            "srt": download_urls["srt"],
        }
        complete_job(
            job_id,
            {
                **result,
                "success": True,
                "status": "complete",
                "transcript": result["text"],
                "files": file_urls,
                "generated_files": files,
                "download_urls": download_urls,
                "duration_seconds": duration_seconds,
                "duration": format_duration(duration_seconds),
            },
        )
    except RuntimeError as exc:
        fail_job(job_id, str(exc))
    except Exception:
        logger.exception("Unexpected transcription job error")
        fail_job(job_id, "Something went wrong while transcribing this file.")
    finally:
        remove_file(uploaded_path)


@app.get("/api/progress/{job_id}")
def progress(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Transcription job not found.")
    return job_progress(job)


@app.get("/api/result/{job_id}")
def result(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Transcription job not found.")
    if job.status == "error":
        raise HTTPException(status_code=500, detail=job.error or "Transcription failed.")
    if job.status != "complete" or job.result is None:
        raise HTTPException(status_code=202, detail="Transcription is still running.")
    return job.result


@app.get("/api/download/{filename}")
def download(filename: str) -> FileResponse:
    safe_name = safe_output_name(filename)
    path = OUTPUT_DIR / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Transcript file not found.")
    return FileResponse(path, filename=safe_name, media_type="text/plain; charset=utf-8")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.head("/")
def index_head() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")
