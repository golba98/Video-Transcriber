from __future__ import annotations

import re
from pathlib import Path
from threading import Lock

from .utils import clean_text, slugify_filename_stem, unique_output_filename

_export_lock = Lock()


def seconds_to_text_timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def seconds_to_srt_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    whole = int(seconds)
    milliseconds = int(round((seconds - whole) * 1000))
    if milliseconds == 1000:
        whole += 1
        milliseconds = 0
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def format_plain_text(segments: list[dict]) -> str:
    sentences = [clean_text(segment["text"]) for segment in segments if segment.get("text")]
    text = " ".join(sentence for sentence in sentences if sentence)
    text = re.sub(r"(?<=[.!?])\s+", "\n\n", text)
    return clean_text(text)


def format_timestamped_text(segments: list[dict]) -> str:
    lines = []
    for segment in segments:
        text = clean_text(segment.get("text", ""))
        if not text:
            continue
        start = seconds_to_text_timestamp(float(segment["start"]))
        end = seconds_to_text_timestamp(float(segment["end"]))
        lines.append(f"[{start} - {end}] {text}")
    return "\n".join(lines).strip()


def format_srt(segments: list[dict]) -> str:
    blocks = []
    number = 1
    for segment in segments:
        text = clean_text(segment.get("text", ""))
        if not text:
            continue
        start = seconds_to_srt_timestamp(float(segment["start"]))
        end = seconds_to_srt_timestamp(float(segment["end"]))
        blocks.append(f"{number}\n{start} --> {end}\n{text}")
        number += 1
    return "\n\n".join(blocks).strip() + ("\n" if blocks else "")


def write_exports(segments: list[dict], output_dir: Path, source_filename: str) -> dict[str, str]:
    plain = format_plain_text(segments)
    timestamped = format_timestamped_text(segments)
    srt = format_srt(segments)
    stem = slugify_filename_stem(source_filename)

    with _export_lock:
        files = {
            "plain": unique_output_filename(output_dir, f"{stem}-transcript.txt"),
            "timestamped": unique_output_filename(output_dir, f"{stem}-timestamped.txt"),
            "srt": unique_output_filename(output_dir, f"{stem}.srt"),
        }

        (output_dir / files["plain"]).write_text(plain, encoding="utf-8")
        (output_dir / files["timestamped"]).write_text(timestamped, encoding="utf-8")
        (output_dir / files["srt"]).write_text(srt, encoding="utf-8")
    return files
