"""Silero voice-activity detection.

The net ships as ONNX inside the faster-whisper wheel, so this needs neither a
torch.hub clone nor network access at run time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .audio import SAMPLE_RATE


@dataclass(frozen=True)
class SpeechRegion:
    start: float
    end: float


@dataclass(frozen=True)
class VadOptions:
    """Silero tuning. These are the values the Mac pipeline shipped with — the
    same net, so they transfer directly."""

    threshold: float = 0.35
    min_speech_duration_ms: int = 250
    max_speech_duration_s: float = 15.0
    min_silence_duration_ms: int = 200
    speech_pad_ms: int = 200


def speech_regions(
    audio: Any,
    sample_rate: int = SAMPLE_RATE,
    options: VadOptions | None = None,
) -> list[SpeechRegion]:
    """Find speech regions across the whole stream; returns seconds."""

    from faster_whisper.vad import (
        VadOptions as FwVadOptions,
        get_speech_timestamps,
    )

    opts = options or VadOptions()
    if sample_rate != SAMPLE_RATE:
        # The bundled net is fixed at 16 kHz; the pipeline always resamples
        # before this call, so a mismatch is a wiring bug, not bad input.
        raise ValueError(
            f"bundled Silero VAD expects {SAMPLE_RATE} Hz audio, got {sample_rate}"
        )

    stamps = get_speech_timestamps(
        audio,
        FwVadOptions(
            threshold=opts.threshold,
            min_speech_duration_ms=opts.min_speech_duration_ms,
            max_speech_duration_s=opts.max_speech_duration_s,
            min_silence_duration_ms=opts.min_silence_duration_ms,
            speech_pad_ms=opts.speech_pad_ms,
        ),
        sampling_rate=sample_rate,
    )
    return [
        SpeechRegion(start=s["start"] / sample_rate, end=s["end"] / sample_rate)
        for s in stamps
    ]
