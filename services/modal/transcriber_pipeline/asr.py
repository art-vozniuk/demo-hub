"""Whisper via faster-whisper (CTranslate2): float16 on GPU, int8 on CPU."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)


# Backend-neutral size tokens → CTranslate2-converted repos. Spelled out rather
# than relying on faster-whisper's own alias table so a change upstream can't
# silently swap our weights.
WHISPER_REPOS: dict[str, str] = {
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "medium": "Systran/faster-whisper-medium",
}

DEFAULT_MODEL = "large-v3-turbo"


@dataclass
class AsrWord:
    start: float
    end: float
    text: str


@dataclass
class AsrSegment:
    """One Whisper segment.

    The three confidence signals are what `filter_hallucinations` reads;
    faster-whisper reports all of them per segment, exactly as MLX-Whisper did.
    """

    start: float
    end: float
    text: str
    words: list[AsrWord] = field(default_factory=list)
    no_speech_prob: float = 0.0
    compression_ratio: float = 0.0
    avg_logprob: float = 0.0

    def shifted(self, offset: float) -> "AsrSegment":
        """Same segment moved `offset` seconds later — VAD chunks are
        transcribed in isolation, so their timestamps start at zero."""

        return replace(
            self,
            start=self.start + offset,
            end=self.end + offset,
            words=[
                AsrWord(w.start + offset, w.end + offset, w.text) for w in self.words
            ],
        )


@dataclass
class AsrResult:
    segments: list[AsrSegment]
    language: str | None = None


def resolve_model(model: str) -> str:
    """Map a size token to a repo id. A value that already looks like a repo id
    (contains "/") passes through; an unknown token falls back to large-v3."""

    if "/" in model:
        return model
    return WHISPER_REPOS.get(model, WHISPER_REPOS["large-v3"])


def cuda_available() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False


def is_cached(model: str) -> bool:
    """True when the resolved repo is already in the local HF cache. Only drives
    a status message, so a false negative is harmless."""

    repo = resolve_model(model)
    hf_home = Path(os.getenv("HF_HOME", Path.home() / ".cache" / "huggingface"))
    repo_dir = hf_home / "hub" / f"models--{repo.replace('/', '--')}"
    return repo_dir.exists() and any(repo_dir.iterdir())


def download(model: str) -> str:
    """Fetch the weights into the local cache without loading them, and return
    the resolved repo id. Lets a CPU container warm a shared volume."""

    from faster_whisper.utils import download_model

    repo = resolve_model(model)
    # faster-whisper's own downloader knows which files a CTranslate2 model
    # needs, so this skips the rest of the repo.
    download_model(repo)
    return repo


class WhisperTranscriber:
    """A loaded Whisper model. Device is fixed at construction — CTranslate2
    offers no way to move one afterwards, which is why the serving container
    builds this only once a GPU is attached."""

    def __init__(self, model: str) -> None:
        from faster_whisper import WhisperModel

        self.model_id = resolve_model(model)
        cuda = cuda_available()
        self.device = "cuda" if cuda else "cpu"
        compute_type = "float16" if cuda else "int8"
        log.info(
            f"loading faster-whisper {self.model_id} on {self.device} ({compute_type})"
        )
        self._model = WhisperModel(
            self.model_id, device=self.device, compute_type=compute_type
        )

    def transcribe(
        self,
        audio: Any,
        *,
        language: str | None = None,
        initial_prompt: str | None = None,
    ) -> AsrResult:
        """Transcribe one float32 16 kHz mono chunk with word timestamps."""

        segments, info = self._model.transcribe(
            audio,
            language=language,
            word_timestamps=True,
            # Each VAD chunk is decoded in isolation; carrying decoder state
            # across chunks is what makes Whisper loop on itself.
            condition_on_previous_text=False,
            initial_prompt=initial_prompt,
            # We ran Silero ourselves and are handing over one speech chunk;
            # faster-whisper defaults this to True, which would re-clip it.
            vad_filter=False,
        )
        # `segments` is a lazy generator — nothing is decoded until it is
        # drained, so materialise it here rather than handing a half-run
        # transcription back to the pipeline.
        return AsrResult(
            segments=[_to_segment(seg) for seg in segments],
            language=info.language,
        )


def _to_segment(seg: Any) -> AsrSegment:
    words = [
        AsrWord(start=float(w.start), end=float(w.end), text=str(w.word))
        for w in (seg.words or [])
    ]
    return AsrSegment(
        start=float(seg.start),
        end=float(seg.end),
        text=str(seg.text),
        words=words,
        no_speech_prob=float(seg.no_speech_prob),
        compression_ratio=float(seg.compression_ratio),
        avg_logprob=float(seg.avg_logprob),
    )
