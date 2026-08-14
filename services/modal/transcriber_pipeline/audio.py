"""Audio decoding: any container/codec → 16 kHz mono float32, via ffmpeg."""

from __future__ import annotations

import logging
import subprocess
import tempfile
import wave

import numpy as np


log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000


def probe_duration(audio_path: str) -> float | None:
    """Container duration in seconds, read from metadata without decoding.

    Lets the caller reject an over-long upload before spending GPU time on it.
    Returns None when the container carries no duration or ffprobe can't read
    it — the caller should then fall back to decoding.
    """

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=True)
        return float(proc.stdout.decode().strip())
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as e:
        log.warning(f"ffprobe could not read a duration from {audio_path}: {e!r}")
        return None


def load_audio(audio_path: str, target_sr: int = SAMPLE_RATE) -> np.ndarray:
    """Decode to a mono float32 array at `target_sr` (raw f32le on stdout)."""

    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-threads",
        "0",
        "-i",
        audio_path,
        "-f",
        "f32le",
        "-ac",
        "1",
        "-ar",
        str(target_sr),
        "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"ffmpeg failed to decode {audio_path}: {stderr}") from e

    audio = np.frombuffer(proc.stdout, dtype=np.float32)
    if audio.size == 0:
        raise RuntimeError(f"ffmpeg decoded 0 samples from {audio_path}")
    # frombuffer views immutable bytes; downstream code (VAD, slicing) wants a
    # writable array it owns.
    return np.array(audio, dtype=np.float32)


def duration_seconds(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
    return len(audio) / float(sample_rate)


def write_wav16k(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> str:
    """Write 16-bit PCM WAV to a temp file for pyannote; return its path.

    stdlib `wave` rather than torchaudio.save: int16 at 16 kHz is exactly what
    the diarizer resamples to anyway, and this keeps the one file both stages
    share free of a codec dependency. Caller owns deletion.
    """

    clipped = np.clip(audio, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    with wave.open(tmp.name, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    return tmp.name
