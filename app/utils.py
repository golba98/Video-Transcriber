from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".mp3"}
MAX_OUTPUT_STEM_LENGTH = 90


def ensure_directories(*paths: Path) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def require_media_tools() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe") if not command_exists(name)]
    if missing:
        raise HTTPException(
            status_code=500,
            detail=(
                "ffmpeg and ffprobe are required for local media decoding. "
                "Install them on Fedora with: sudo dnf install ffmpeg -y"
            ),
        )


def validate_upload(file: UploadFile) -> str:
    original_name = file.filename or ""
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Please upload one of: {allowed}.",
        )
    return extension


async def save_upload(file: UploadFile, upload_dir: Path, extension: str) -> Path:
    target = upload_dir / f"{uuid4().hex}{extension}"
    bytes_written = 0

    try:
        with target.open("wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                bytes_written += len(chunk)
                buffer.write(chunk)
    except Exception:
        logger.exception("Failed to save uploaded file")
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Could not save the uploaded file.")

    if bytes_written == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    return target


def probe_duration_seconds(path: Path) -> float | None:
    if not command_exists("ffprobe"):
        return None

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(completed.stdout or "{}")
        duration = data.get("format", {}).get("duration")
        return float(duration) if duration is not None else None
    except Exception:
        logger.exception("Could not probe duration for %s", path)
        return None


def clean_text(text: str) -> str:
    normalized = re.sub(r"[ \t]+", " ", text)
    normalized = re.sub(r"\s+\n", "\n", normalized)
    normalized = re.sub(r"\n\s+", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def format_duration(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def safe_output_name(name: str) -> str:
    candidate = Path(name).name
    if candidate != name or not candidate:
        raise HTTPException(status_code=400, detail="Invalid download filename.")
    return candidate


def slugify_filename_stem(filename: str) -> str:
    stem = Path(filename or "transcript").stem.lower()
    stem = re.sub(r"[^a-z0-9]+", "-", stem)
    stem = re.sub(r"-{2,}", "-", stem).strip("-")
    if not stem:
        stem = "transcript"
    return stem[:MAX_OUTPUT_STEM_LENGTH].strip("-") or "transcript"


def unique_output_filename(output_dir: Path, filename: str) -> str:
    path = output_dir / filename
    if not path.exists():
        return filename

    stem = path.stem
    suffix = path.suffix
    counter = 2
    while True:
        candidate = f"{stem}-{counter}{suffix}"
        if not (output_dir / candidate).exists():
            return candidate
        counter += 1


def remove_file(path: Path | None) -> None:
    if not path:
        return
    try:
        path.unlink(missing_ok=True)
    except Exception:
        logger.warning("Could not remove temporary file %s", path, exc_info=True)
