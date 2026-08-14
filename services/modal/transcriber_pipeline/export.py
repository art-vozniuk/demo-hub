"""Transcript rendering: .txt, .srt and the canonical .json."""

from __future__ import annotations

import json
from typing import Any


def _fmt_ts(seconds: float, srt: bool = False) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds % 1) * 1000))
    if srt:
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    return f"{m:02d}:{s:02d}"


def to_txt(segments: list[dict]) -> str:
    lines = []
    for seg in segments:
        start = _fmt_ts(seg["start"])
        end = _fmt_ts(seg["end"])
        lines.append(f"[{start} - {end}] {seg['speaker']}\n{seg['text']}\n")
    return "\n".join(lines)


def to_srt(segments: list[dict]) -> str:
    blocks = []
    for i, seg in enumerate(segments, 1):
        start = _fmt_ts(seg["start"], srt=True)
        end = _fmt_ts(seg["end"], srt=True)
        blocks.append(f"{i}\n{start} --> {end}\n[{seg['speaker']}] {seg['text']}")
    return "\n\n".join(blocks) + "\n"


def to_payload(segments: list[dict]) -> list[dict]:
    """Segments trimmed to what a consumer renders: no per-word timings (they
    triple the size and nothing downstream reads them) and timestamps rounded
    to milliseconds."""

    return [
        {
            "start": round(float(seg["start"]), 3),
            "end": round(float(seg["end"]), 3),
            "speaker": seg["speaker"],
            "text": seg["text"],
        }
        for seg in segments
    ]


def to_json(segments: list[dict], meta: dict[str, Any] | None = None) -> str:
    """A `meta` block plus trimmed segments — the artifact the SPA fetches."""

    return json.dumps(
        {"meta": meta or {}, "segments": to_payload(segments)},
        ensure_ascii=False,
        indent=2,
    )
