"""Pulling an audio track out of a media container with ffmpeg.

A video upload is mostly video: a 90-minute recording can be gigabytes of
frames wrapped around a few dozen megabytes of speech. Demuxing it to audio on
a cheap CPU container first means the GPU never downloads, stores or decodes
any of that — it gets a small lossless audio file instead.
"""

from __future__ import annotations

import logging
import os
import subprocess

log = logging.getLogger(__name__)


# 16 kHz mono is exactly what both Whisper and the diarizer resample to, and
# FLAC is lossless, so extraction cannot cost transcription accuracy while
# still cutting a 90-minute track to well under 100 MB.
EXTRACT_SAMPLE_RATE = 16_000
EXTRACT_EXTENSION = "flac"


class NoAudioStreamError(RuntimeError):
    """The container carries no audio — a silent screen recording, say."""


def _run(cmd: list[str], what: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, check=True)
    except FileNotFoundError as e:
        raise RuntimeError(f"{cmd[0]} is not installed in this image") from e
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"{what} failed: {stderr[-2000:]}") from e


def probe_media(path: str) -> dict[str, object]:
    """Container facts needed before committing to a decode: duration, whether
    there is an audio stream at all, and whether there is video.

    One ffprobe call over both stream lists — cheap (metadata only) and it
    answers the "is this really a video?" question that an extension can't.
    """

    proc = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type",
            "-of",
            "default=noprint_wrappers=1",
            path,
        ],
        "ffprobe",
    )

    duration: float | None = None
    codec_types: list[str] = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        key, _, value = line.partition("=")
        if key == "duration":
            try:
                duration = float(value)
            except ValueError:
                pass
        elif key == "codec_type":
            codec_types.append(value)

    return {
        "duration_s": duration,
        "has_audio": "audio" in codec_types,
        "has_video": "video" in codec_types,
        "streams": codec_types,
    }


def extract_audio(source_path: str, dest_path: str) -> None:
    """Write the first audio stream of `source_path` to `dest_path` as
    16 kHz mono FLAC, dropping video and every other stream."""

    _run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            source_path,
            # Drop video and subtitles, and take only the first audio stream —
            # a camera file often carries several.
            "-vn",
            "-sn",
            "-dn",
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            str(EXTRACT_SAMPLE_RATE),
            "-c:a",
            "flac",
            dest_path,
        ],
        "ffmpeg audio extraction",
    )
    if not os.path.exists(dest_path) or os.path.getsize(dest_path) == 0:
        raise RuntimeError("ffmpeg produced an empty audio file")
    log.info(
        f"extracted {os.path.getsize(dest_path) / (1024 * 1024):.1f} MB of "
        f"{EXTRACT_EXTENSION} from "
        f"{os.path.getsize(source_path) / (1024 * 1024):.1f} MB of source"
    )
