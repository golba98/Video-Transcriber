from __future__ import annotations

import logging
from ctypes.util import find_library
from functools import lru_cache
from pathlib import Path
from typing import Callable

import ctranslate2
from faster_whisper import WhisperModel

from .exports import format_plain_text, format_srt, format_timestamped_text

logger = logging.getLogger(__name__)

SUPPORTED_MODELS = {"tiny", "base", "small", "medium", "large-v3"}
DEFAULT_MODEL = "small"


def cuda_available() -> bool:
    try:
        has_device = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        logger.debug("CUDA availability check failed", exc_info=True)
        return False
    if not has_device:
        return False
    if not find_library("cublas"):
        logger.info("CUDA device detected, but libcublas is not available; using CPU")
        return False
    return True


def default_runtime() -> dict[str, str | bool]:
    has_cuda = cuda_available()
    return {
        "cuda_available": has_cuda,
        "device": "cuda" if has_cuda else "cpu",
        "compute_type": "float16" if has_cuda else "int8",
    }


@lru_cache(maxsize=8)
def get_model(model_name: str, device: str, compute_type: str) -> WhisperModel:
    logger.info("Loading faster-whisper model=%s device=%s compute_type=%s", model_name, device, compute_type)
    return WhisperModel(model_name, device=device, compute_type=compute_type)


def normalize_model_name(model_name: str | None) -> str:
    if not model_name:
        return DEFAULT_MODEL
    if model_name not in SUPPORTED_MODELS:
        raise ValueError(f"Unsupported model '{model_name}'.")
    return model_name


def normalize_language(language: str | None) -> str | None:
    if not language or language == "auto":
        return None
    return language


ProgressCallback = Callable[[str, float | None, str], None]


def transcribe_media(
    path: Path,
    model_name: str | None,
    language: str | None,
    output_format: str,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    selected_model = normalize_model_name(model_name)
    runtime = default_runtime()

    try:
        segments, info = _run_transcription(path, selected_model, language, runtime, progress_callback)
    except Exception:
        logger.exception("Transcription failed for %s", path)
        raise RuntimeError("Transcription failed. Try a smaller file, a smaller model, or confirm ffmpeg can decode this media.")

    if output_format == "srt":
        preview = format_srt(segments)
    elif output_format == "timestamped":
        preview = format_timestamped_text(segments)
    else:
        preview = format_plain_text(segments)

    return {
        "text": format_plain_text(segments),
        "timestamped_text": format_timestamped_text(segments),
        "srt": format_srt(segments),
        "preview": preview,
        "segments": segments,
        "detected_language": getattr(info, "language", None),
        "language_probability": getattr(info, "language_probability", None),
        "model": selected_model,
        "device": runtime["device"],
        "compute_type": runtime["compute_type"],
    }


def _run_transcription(
    path: Path,
    model_name: str,
    language: str | None,
    runtime: dict,
    progress_callback: ProgressCallback | None,
) -> tuple[list[dict], object]:
    attempts = [(str(runtime["device"]), str(runtime["compute_type"]))]
    if attempts[0][0] == "cuda":
        attempts.append(("cpu", "int8"))

    last_error: Exception | None = None
    for device, compute_type in attempts:
        try:
            if progress_callback:
                progress_callback("loading_model", None, "Loading model")
            model = get_model(model_name, device, compute_type)
            if progress_callback:
                progress_callback("transcribing", 0.0, "Transcribing")
            segments_iter, info = model.transcribe(
                str(path),
                language=normalize_language(language),
                vad_filter=True,
                beam_size=5,
            )
            segments = []
            for index, segment in enumerate(segments_iter, start=1):
                item = {
                    "id": index,
                    "start": float(segment.start),
                    "end": float(segment.end),
                    "text": segment.text.strip(),
                }
                segments.append(item)
                if progress_callback:
                    end_time = float(segment.end)
                    progress_callback("transcribing", end_time, f"Transcribing {end_time:.1f}s")
            runtime["device"] = device
            runtime["compute_type"] = compute_type
            return segments, info
        except Exception as exc:
            last_error = exc
            if device == "cuda":
                logger.warning("CUDA transcription failed; retrying on CPU", exc_info=True)
                continue
            raise

    raise RuntimeError("Transcription failed") from last_error
