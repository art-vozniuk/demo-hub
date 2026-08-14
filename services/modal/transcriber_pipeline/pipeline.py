"""Orchestration: VAD chunking → Whisper → filter → diarization → merge.

The stage logic here is the port's whole point of fidelity — it is the same as
the Mac pipeline's, only the runtimes underneath differ (see the package
docstring).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from . import asr as asr_module
from .audio import SAMPLE_RATE, duration_seconds, load_audio, write_wav16k
from .asr import DEFAULT_MODEL, AsrSegment, WhisperTranscriber
from .vad import SpeechRegion, VadOptions, speech_regions


log = logging.getLogger(__name__)

StatusCallback = Callable[[str, str, str], None]

DIARIZATION_MODEL = "pyannote/speaker-diarization-3.1"

# Whisper decodes a chunk in isolation; anything shorter than this is noise the
# VAD let through, and decoding it invites hallucinated filler.
MIN_CHUNK_SECONDS = 0.3

# VAD regions closer together than this are transcribed as one chunk, so short
# utterances still get sentence-level context.
CHUNK_MERGE_GAP_SECONDS = 0.3

# Hallucination thresholds, matched to Whisper's own decoding fallbacks.
MAX_NO_SPEECH_PROB = 0.6
MAX_COMPRESSION_RATIO = 2.4
MIN_AVG_LOGPROB = -1.0

# Segment merging limits: keep a turn readable rather than one wall of text.
MERGE_MAX_GAP_S = 1.5
MERGE_MAX_DURATION_S = 30.0
MERGE_MAX_WORDS = 50

# A run of at most this many words surrounded by one other speaker is treated
# as diarization flicker and reassigned.
FLICKER_RUN_WORDS = 2

# Punctuation examples nudge Whisper into punctuating at all; only languages we
# have a hand-checked sample for.
PUNCTUATION_PROMPTS = {
    "ru": "Привет! Как дела? Да, всё хорошо. Ну, в общем, вот так.",
    "en": "Hello! How are you? Yes, everything is fine. Well, that's how it is.",
}


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Duration of the overlap between two time intervals."""

    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _emit(
    on_status: StatusCallback | None, stage_key: str, title: str, detail: str
) -> None:
    if on_status:
        on_status(stage_key, title, detail)


def auth_kwargs(from_pretrained: Callable, token: str | None) -> dict[str, str]:
    """How to pass the HF token to pyannote's `from_pretrained`.

    pyannote renamed the argument between majors: 3.x takes `use_auth_token`,
    4.x takes `token`. Hard-coding either spelling makes the pin and the call
    site silently coupled — and it broke exactly that way once, at container
    start-up in production. So ask the installed function which it accepts.

    Returns {} when it declares neither, or when there is no token: pyannote
    resolves credentials through huggingface_hub, which reads HF_TOKEN from the
    environment on its own.
    """

    import inspect

    if not token:
        return {}
    parameters = inspect.signature(from_pretrained).parameters
    for name in ("token", "use_auth_token"):
        if name in parameters:
            return {name: token}
    log.warning(
        "pyannote's from_pretrained declares neither `token` nor "
        "`use_auth_token`; relying on HF_TOKEN in the environment"
    )
    return {}


@dataclass
class TranscriptionResult:
    """Everything one run produced: the transcript plus the metadata a job
    runner stores next to it."""

    segments: list[dict] = field(default_factory=list)
    language: str | None = None
    duration_s: float = 0.0
    model_id: str = ""

    @property
    def speakers(self) -> list[str]:
        return sorted({seg["speaker"] for seg in self.segments if seg.get("speaker")})


class TranscriptionPipeline:
    """End-to-end: Whisper (ASR) + pyannote.audio (diarization).

    Models are loaded lazily and cached on the instance, so a serving container
    builds one pipeline and reuses it across requests. `warmup()` and
    `move_to_device()` exist for the memory-snapshot split — see
    services/modal/transcriber/app.py.
    """

    def __init__(
        self,
        hf_token: str,
        whisper_model: str = DEFAULT_MODEL,
        glossary: str = "",
    ) -> None:
        self.hf_token = hf_token
        self.whisper_model = whisper_model
        self.glossary = glossary
        self._diarizer = None
        self._transcribers: dict[str, WhisperTranscriber] = {}
        self._cleanup_llm = None

    # ── model lifecycle ───────────────────────────────────────────────────

    def load_asr(self, model: str | None = None) -> WhisperTranscriber:
        """Load (and cache) a Whisper model. Switching sizes between requests
        costs a load only the first time each size is asked for."""

        repo = asr_module.resolve_model(model or self.whisper_model)
        if repo not in self._transcribers:
            self._transcribers[repo] = WhisperTranscriber(repo)
        return self._transcribers[repo]

    def load_diarizer(self, on_status: StatusCallback | None = None):
        """Load (and cache) the pyannote diarization pipeline."""

        if self._diarizer is not None:
            _emit(
                on_status,
                "diarizer_model",
                "Speaker diarization model",
                f"Using in-memory pipeline {DIARIZATION_MODEL}",
            )
            return self._diarizer

        from pyannote.audio import Pipeline as PyannotePipeline

        _emit(
            on_status,
            "diarizer_model",
            "Speaker diarization model",
            f"Loading model {DIARIZATION_MODEL}",
        )
        diarizer = PyannotePipeline.from_pretrained(
            DIARIZATION_MODEL,
            **auth_kwargs(PyannotePipeline.from_pretrained, self.hf_token),
        )
        if diarizer is None:
            # from_pretrained returns None (rather than raising) when the token
            # can't read the gated repo — say so plainly.
            raise RuntimeError(
                f"Could not load {DIARIZATION_MODEL}. Accept the model terms on "
                "huggingface.co for both pyannote/speaker-diarization-3.1 and "
                "pyannote/segmentation-3.0 with the account owning HF_TOKEN."
            )
        self._diarizer = diarizer
        self.move_to_device()
        return self._diarizer

    def load_cleanup_llm(self):
        """Load (and cache) the cleanup LLM. Deliberately lazy and never part of
        warmup: it is several GB for a feature that is off by default, and a
        container that is never asked for it should never pay."""

        if self._cleanup_llm is None:
            from .llm import CleanupLlm

            self._cleanup_llm = CleanupLlm()
        return self._cleanup_llm

    def warmup(self, *, asr: bool = True, diarizer: bool = True) -> None:
        """Load models up front so the first request doesn't pay for it.

        The flags exist because of how snapshotting works: the diarizer is
        plain torch and can be loaded before a GPU is attached and moved later,
        while a CTranslate2 Whisper model is bound to its device at
        construction and has to wait until the GPU is actually there.
        """

        if diarizer:
            self.load_diarizer()
        if asr:
            self.load_asr()

    def move_to_device(self) -> None:
        """Place the diarizer on the best device available right now — called
        again after a snapshot restore, once the GPU has appeared."""

        if self._diarizer is None:
            return
        import torch

        device = torch.device("cuda" if asr_module.cuda_available() else "cpu")
        self._diarizer.to(device)
        log.info(f"diarizer on {device}")

    # ── transcription ─────────────────────────────────────────────────────

    def _initial_prompt(self, language: str | None) -> str | None:
        """Whisper's decoder context: a punctuation example plus glossary terms,
        which raises the odds it spells domain words the way we want."""

        parts = []
        if language and language in PUNCTUATION_PROMPTS:
            parts.append(PUNCTUATION_PROMPTS[language])
        if self.glossary:
            parts.append(self.glossary)
        return " ".join(parts) if parts else None

    @staticmethod
    def merge_vad_regions(regions: list[SpeechRegion]) -> list[SpeechRegion]:
        merged: list[SpeechRegion] = []
        for r in regions:
            if merged and r.start - merged[-1].end < CHUNK_MERGE_GAP_SECONDS:
                merged[-1] = SpeechRegion(start=merged[-1].start, end=r.end)
            else:
                merged.append(r)
        return merged

    @staticmethod
    def filter_hallucinations(segments: list[AsrSegment]) -> list[AsrSegment]:
        """Drop segments Whisper itself is unsure about: silence it decoded
        anyway, repetition loops, and low-confidence output."""

        kept = []
        for seg in segments:
            if seg.no_speech_prob > MAX_NO_SPEECH_PROB:
                continue
            if seg.compression_ratio > MAX_COMPRESSION_RATIO:
                continue
            if seg.avg_logprob < MIN_AVG_LOGPROB:
                continue
            if not seg.text.strip():
                continue
            kept.append(seg)
        return kept

    def transcribe(
        self,
        audio: np.ndarray,
        language: str | None = None,
        model: str | None = None,
        on_status: StatusCallback | None = None,
    ) -> tuple[list[AsrSegment], str | None]:
        """Run VAD to find speech chunks, then transcribe each one. Shorter
        chunks give more accurate segments than one pass over the whole file.

        Returns the surviving segments plus the language actually decoded.
        """

        _emit(
            on_status,
            "vad",
            "Voice activity detection",
            "Running Silero VAD on the full audio stream",
        )
        regions = speech_regions(audio, SAMPLE_RATE, VadOptions())
        chunks = self.merge_vad_regions(regions)
        _emit(
            on_status,
            "vad",
            "Voice activity detection",
            f"Detected {len(regions)} speech regions and merged them into "
            f"{len(chunks)} transcription chunks",
        )

        requested = model or self.whisper_model
        _emit(
            on_status,
            "whisper_model",
            "Whisper model",
            f"{'Using cached' if asr_module.is_cached(requested) else 'Downloading'} "
            f"model {requested}",
        )
        transcriber = self.load_asr(requested)
        prompt = self._initial_prompt(language)

        all_segments: list[AsrSegment] = []
        detected_language = language
        for idx, region in enumerate(chunks, start=1):
            chunk = audio[
                int(region.start * SAMPLE_RATE) : int(region.end * SAMPLE_RATE)
            ]
            if len(chunk) < SAMPLE_RATE * MIN_CHUNK_SECONDS:
                continue

            _emit(
                on_status,
                "transcribe",
                "Transcription",
                f"Transcribing chunk {idx}/{len(chunks)} "
                f"({len(chunk) / SAMPLE_RATE:.1f}s, {len(chunk):,} samples)",
            )
            result = transcriber.transcribe(
                chunk, language=language, initial_prompt=prompt
            )
            if detected_language is None and result.language:
                detected_language = result.language
            all_segments.extend(seg.shifted(region.start) for seg in result.segments)

        kept = self.filter_hallucinations(all_segments)
        _emit(
            on_status,
            "transcribe",
            "Transcription",
            f"Finished {len(chunks)} chunks and kept {len(kept)} transcript "
            "segments after filtering",
        )
        return kept, detected_language

    # ── diarization ───────────────────────────────────────────────────────

    def diarize(
        self,
        wav_path: str,
        segments: list[AsrSegment],
        num_speakers: int | None = None,
        on_status: StatusCallback | None = None,
    ) -> list[dict]:
        """Assign a speaker per word, then group words into speaker turns."""

        diarizer = self.load_diarizer(on_status=on_status)

        kwargs: dict = {}
        if num_speakers:
            kwargs["num_speakers"] = num_speakers
        _emit(
            on_status,
            "diarize",
            "Speaker diarization",
            f"Running diarization with "
            f"{f'num_speakers={num_speakers}' if num_speakers else 'automatic speaker count'}",
        )
        turns = self._speaker_turns(diarizer(wav_path, **kwargs))
        _emit(
            on_status,
            "diarize",
            "Speaker diarization",
            f"Matching transcript words to {len(turns)} speaker turns",
        )

        labeled = self.assign_speakers(segments, turns)
        if not labeled:
            _emit(
                on_status,
                "diarize",
                "Speaker diarization",
                "No words were available for speaker assignment",
            )
            return []

        merged = self.merge_consecutive(self.group_by_speaker(labeled))
        _emit(
            on_status,
            "diarize",
            "Speaker diarization",
            f"Built {len(merged)} speaker segments from {len(labeled)} labeled words",
        )
        return merged

    @staticmethod
    def _speaker_turns(annotation) -> list[tuple[float, float, str]]:
        """Flatten pyannote output to (start, end, speaker). 4.x wraps the
        result in DiarizeOutput; 3.x hands back the Annotation directly."""

        if hasattr(annotation, "speaker_diarization"):
            diarization = annotation.speaker_diarization
        elif hasattr(annotation, "annotation"):
            diarization = annotation.annotation
        else:
            diarization = annotation
        return [
            (turn.start, turn.end, spk)
            for turn, _, spk in diarization.itertracks(yield_label=True)
        ]

    @staticmethod
    def assign_speakers(
        segments: list[AsrSegment],
        turns: list[tuple[float, float, str]],
    ) -> list[dict]:
        """Label each word with the speaker whose turn it overlaps most, then
        smooth flicker: a one- or two-word run bracketed by the same other
        speaker is diarization noise, not a real interjection."""

        words: list[dict] = []
        for seg in segments:
            for w in seg.words:
                text = w.text.strip()
                if not text:
                    continue
                best_spk, best_ov = "SPEAKER_00", 0.0
                for t_start, t_end, spk in turns:
                    ov = _overlap(w.start, w.end, t_start, t_end)
                    if ov > best_ov:
                        best_ov, best_spk = ov, spk
                words.append(
                    {
                        "start": w.start,
                        "end": w.end,
                        "text": text,
                        "speaker": best_spk,
                    }
                )

        for i in range(1, max(0, len(words) - 1)):
            cur = words[i]["speaker"]
            prev = words[i - 1]["speaker"]
            if prev == cur:
                continue
            j = i
            while j < len(words) and words[j]["speaker"] == cur:
                j += 1
            run_len = j - i
            nxt = words[j]["speaker"] if j < len(words) else prev
            if run_len <= FLICKER_RUN_WORDS and prev == nxt:
                for k in range(i, j):
                    words[k]["speaker"] = prev

        return words

    @staticmethod
    def group_by_speaker(words: list[dict]) -> list[dict]:
        """Consecutive words by the same speaker become one segment."""

        if not words:
            return []

        grouped: list[dict] = []
        cur = {**words[0], "words": [words[0]]}
        for w in words[1:]:
            if w["speaker"] == cur["speaker"]:
                cur["end"] = w["end"]
                cur["text"] += " " + w["text"]
                cur["words"].append(w)
            else:
                grouped.append(cur)
                cur = {**w, "words": [w]}
        grouped.append(cur)
        return grouped

    @staticmethod
    def merge_consecutive(segments: list[dict]) -> list[dict]:
        """Merge adjacent same-speaker segments, respecting the gap, duration
        and word-count limits that keep a turn readable."""

        if not segments:
            return segments

        merged = [segments[0].copy()]
        for seg in segments[1:]:
            prev = merged[-1]
            can_merge = (
                seg["speaker"] == prev["speaker"]
                and seg["start"] - prev["end"] <= MERGE_MAX_GAP_S
                and prev["end"] - prev["start"] < MERGE_MAX_DURATION_S
                and len(prev.get("words", [])) < MERGE_MAX_WORDS
            )
            if can_merge:
                prev["end"] = seg["end"]
                prev["text"] += " " + seg["text"]
                # Copy first: the input segment's own list must not be aliased
                # into the merged one.
                prev["words"] = [*prev.get("words", []), *seg.get("words", [])]
            else:
                merged.append(seg.copy())
        return merged

    # ── full run ──────────────────────────────────────────────────────────

    def run(
        self,
        audio_path: str,
        language: str | None = None,
        model: str | None = None,
        num_speakers: int | None = None,
        llm_cleanup: bool = False,
        on_status: StatusCallback | None = None,
    ) -> TranscriptionResult:
        _emit(
            on_status,
            "audio",
            "Audio preparation",
            "Loading source audio and converting it to 16 kHz mono",
        )
        audio = load_audio(audio_path)
        total_s = duration_seconds(audio)
        _emit(
            on_status,
            "audio",
            "Audio preparation",
            f"Loaded {len(audio):,} samples ({total_s:.1f}s of audio)",
        )

        asr_segments, detected_language = self.transcribe(
            audio, language=language, model=model, on_status=on_status
        )

        _emit(
            on_status,
            "wav_export",
            "Temporary WAV export",
            "Preparing a 16 kHz WAV copy for speaker diarization",
        )
        wav_path = write_wav16k(audio)
        try:
            segments = self.diarize(
                wav_path, asr_segments, num_speakers=num_speakers, on_status=on_status
            )
        finally:
            os.unlink(wav_path)

        if llm_cleanup:
            from .postprocess import postprocess_segments

            _emit(on_status, "llm_model", "LLM model", "Loading the cleanup model")
            segments = postprocess_segments(
                segments,
                llm=self.load_cleanup_llm(),
                glossary=self.glossary,
                on_status=on_status,
            )

        _emit(
            on_status,
            "finalize",
            "Final transcript",
            f"Prepared {len(segments)} transcript segments",
        )
        return TranscriptionResult(
            segments=segments,
            language=detected_language,
            duration_s=total_s,
            model_id=asr_module.resolve_model(model or self.whisper_model),
        )
