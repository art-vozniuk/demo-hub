"""Modal app: audio → diarized transcript on a cheap GPU.

Silero VAD → faster-whisper (CTranslate2, float16) per speech chunk →
hallucination filter → pyannote speaker turns → word-level speaker assignment
→ segment merge, with optional LLM cleanup. The pipeline lives in
services/modal/transcriber_pipeline and ships into the image as a local source
package.

The container owns the whole job: download the upload from S3, run the
pipeline, render .json/.txt/.srt and upload all three back to S3. Dispatch only
forwards the URLs, so a long transcript never travels through RabbitMQ or lands
in Postgres.

Endpoint-less: invoked by name through the gateway.
Deploy / preload via services/modal/transcriber/{deploy,preload,preload_llm}.py.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import modal

from common.constants import MODAL_FUNCTION_TIMEOUT_SECONDS
from common.instrument import InferenceRunner
from common.lib import (
    MODEL_DIR,
    configure_logging,
    download_from_s3,
    make_app,
    upload_to_s3,
)
from common.sentry import init_sentry


# L4: 24GB Ada at $0.80/h — the cheapest tier that fits Whisper large-v3
# (~3GB), pyannote (~1.5GB) and, when cleanup is on, a 4-bit 7B (~5.5GB) at
# once. A T4 ($0.59/h, 16GB) also works with cleanup off and is a one-line
# change; it is ~2x slower on large-v3 and has no bf16.
GPU_NAME = "L4"
SCALEDOWN_WINDOW_S = 10

# HF cache on the volume: Whisper, pyannote and (optionally) the cleanup LLM all
# resolve through huggingface_hub, so one env var puts every weight there.
HF_CACHE_DIR = f"{MODEL_DIR}/hf_cache"

# Whisper sizes the UI can ask for. Restricted so a payload can't make the
# container download an arbitrary repo.
ALLOWED_MODELS = ("large-v3", "large-v3-turbo", "medium")
DEFAULT_MODEL = "large-v3-turbo"

# Languages the UI offers. None/absent means auto-detect.
ALLOWED_LANGUAGES = (
    "ru",
    "en",
    "de",
    "fr",
    "es",
    "it",
    "ja",
    "zh",
    "pt",
    "ko",
    "uk",
    "pl",
)

MAX_SPEAKERS = 10

# The dispatch worker gives up at MODAL_FUNCTION_TIMEOUT_SECONDS (600s), and the
# Modal function times out at the same moment by design. Warm throughput on an
# L4 is roughly 8-15x realtime end to end, so 30 minutes of audio is ~2-4
# minutes of compute — inside the budget with room for a cold start.
MAX_AUDIO_SECONDS = 30 * 60
# Cleanup is one LLM generation per segment, which dominates the run; hold it to
# a shorter ceiling rather than letting it eat the whole deadline.
LLM_MAX_AUDIO_SECONDS = 15 * 60

# Segments inlined in the response so the UI can render immediately; the rest
# comes from the JSON in S3.
PREVIEW_SEGMENTS = 20


log = configure_logging("transcriber")
app, volume = make_app("demo-hub-transcriber", "transcriber-models")


# cudnn-runtime, not plain runtime: CTranslate2's wheel is built against CUDA
# 12.4 + cuDNN 9 and dlopens both, but (unlike torch) declares no nvidia pip
# deps, so the libs have to come from the base image.
transcriber_image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04", add_python="3.11"
    )
    # ffmpeg decodes m4a/opus/webm uploads; ffprobe reads their duration
    # without decoding.
    .apt_install("ffmpeg")
    .pip_install(
        # cu124 wheels, matching the base image above.
        "torch==2.6.0",
        "torchaudio==2.6.0",
    )
    .pip_install(
        "faster-whisper==1.2.1",
        "pyannote.audio==3.3.2",
        # Cleanup LLM (optional at run time, always installed: it is small
        # compared with torch and keeps one image for both paths).
        "transformers==4.46.3",
        "accelerate==1.2.1",
        "bitsandbytes>=0.44.0",
        "huggingface-hub[hf-transfer]>=0.34.0",
        "numpy",
        "boto3==1.35.92",
        "sentry-sdk>=2.42.0",
    )
    .env(
        {
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
            "HF_HOME": HF_CACHE_DIR,
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    .add_local_python_source(
        "common.lib",
        "common.instrument",
        "common.constants",
        "common.sentry",
        "transcriber_pipeline",
    )
)


with transcriber_image.imports():
    from transcriber_pipeline import asr, llm
    from transcriber_pipeline.audio import probe_duration
    from transcriber_pipeline.export import to_json, to_payload, to_srt, to_txt
    from transcriber_pipeline.pipeline import TranscriptionPipeline


def _hf_token() -> str:
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError(
            "HF_TOKEN is not set. pyannote/speaker-diarization-3.1 is gated: "
            "create the `huggingface` Modal secret and accept the terms for "
            "both speaker-diarization-3.1 and segmentation-3.0."
        )
    return token


@app.function(
    image=transcriber_image,
    volumes={MODEL_DIR: volume},
    timeout=60 * 60,
    cpu=4.0,
    memory=8192,
    secrets=[modal.Secret.from_name("huggingface")],
)
def preload_weights() -> list[str]:
    """One-shot: fill the volume with every Whisper size the UI can ask for,
    plus the pyannote pipeline and its transitive repos. Re-running is a no-op
    beyond cache checks."""

    os.makedirs(HF_CACHE_DIR, exist_ok=True)
    loaded: list[str] = []

    # Instantiating the pyannote pipeline (rather than snapshot_download-ing one
    # repo) is what pulls segmentation-3.0 and the speaker-embedding model too —
    # they're referenced from its config, not from its repo.
    t0 = time.perf_counter()
    pipeline = TranscriptionPipeline(hf_token=_hf_token())
    pipeline.load_diarizer()
    log.info(f"preload: pyannote ready in {time.perf_counter() - t0:.1f}s")
    loaded.append("pyannote/speaker-diarization-3.1")

    for model in ALLOWED_MODELS:
        t1 = time.perf_counter()
        # Download only — building the model would need a GPU for float16 and
        # would hold every size in memory at once for nothing.
        repo = asr.download(model)
        log.info(
            f"preload: {model} ({repo}) fetched in {time.perf_counter() - t1:.1f}s"
        )
        loaded.append(repo)

    volume.commit()
    log.info(f"preload: volume.commit done; {len(loaded)} repos cached")
    return loaded


@app.function(
    image=transcriber_image,
    volumes={MODEL_DIR: volume},
    timeout=60 * 60,
    cpu=4.0,
    memory=16384,
    secrets=[modal.Secret.from_name("huggingface")],
)
def preload_llm_weights() -> str:
    """Separate one-shot for the cleanup LLM (~15GB for Qwen2.5-7B in bf16,
    quantised to 4-bit at load). Kept out of preload_weights so the default
    volume stays small — `llm_cleanup` requests fail with a pointer here until
    this has run."""

    from huggingface_hub import snapshot_download

    log.info(f"preload: downloading {llm.LLM_MODEL}")
    t0 = time.perf_counter()
    snapshot_download(
        repo_id=llm.LLM_MODEL,
        token=os.environ.get("HF_TOKEN"),
        max_workers=8,
    )
    log.info(f"preload: {llm.LLM_MODEL} downloaded in {time.perf_counter() - t0:.1f}s")
    volume.commit()
    return llm.LLM_MODEL


class StageTimer:
    """Turns the pipeline's on_status stream into per-stage timings.

    The pipeline reports (stage_key, title, detail) as it moves along and the
    keys are stable (audio, vad, transcribe, diarize, llm, ...), so tracking
    transitions gives a real stage breakdown for Grafana and a Sentry waterfall
    — without the pipeline knowing about either.
    """

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self.intervals: list[tuple[str, float, float]] = []
        self._key: str | None = None
        self._started: float = 0.0

    def __call__(self, stage_key: str, title: str, detail: str) -> None:
        now = time.time()
        if self._key is not None and self._key != stage_key:
            self.intervals.append((self._key, self._started, now))
            self._started = now
        elif self._key is None:
            self._started = now
        self._key = stage_key
        log.info(f"[{self.request_id}] {title}: {detail}")

    def finish(self) -> None:
        if self._key is not None:
            self.intervals.append((self._key, self._started, time.time()))
            self._key = None


def _validate_model(raw: Any) -> str:
    if raw is None:
        return DEFAULT_MODEL
    if raw not in ALLOWED_MODELS:
        raise ValueError(f"unsupported model {raw!r}; expected one of {ALLOWED_MODELS}")
    return raw


def _validate_language(raw: Any) -> str | None:
    if raw is None or raw == "" or raw == "auto":
        return None
    if raw not in ALLOWED_LANGUAGES:
        raise ValueError(
            f"unsupported language {raw!r}; expected one of {ALLOWED_LANGUAGES}"
        )
    return raw


def _validate_speakers(raw: Any) -> int | None:
    if raw is None:
        return None
    value = int(raw)
    if value <= 0:
        return None
    if value > MAX_SPEAKERS:
        raise ValueError(f"num_speakers must be <= {MAX_SPEAKERS}, got {value}")
    return value


@app.cls(
    image=transcriber_image,
    gpu=GPU_NAME,
    volumes={MODEL_DIR: volume},
    scaledown_window=SCALEDOWN_WINDOW_S,
    timeout=MODAL_FUNCTION_TIMEOUT_SECONDS,
    enable_memory_snapshot=True,
    secrets=[
        modal.Secret.from_name("supabase-s3"),
        modal.Secret.from_name("huggingface"),
        modal.Secret.from_name("sentry"),
    ],
)
@modal.concurrent(max_inputs=1)
class TranscriberInference:
    @modal.enter(snap=True)
    def load_to_cpu(self) -> None:
        """Snapshot hook (CPU-only container): import the world and load the
        diarizer. Whisper is deliberately *not* loaded here — a CTranslate2
        model binds to its device at construction, so one built now would be
        stuck on the CPU after restore."""

        log.info("snapshot-load: load_to_cpu() begin (CPU-only container)")
        t0 = time.perf_counter()

        self.pipeline = TranscriptionPipeline(
            hf_token=_hf_token(), whisper_model=DEFAULT_MODEL
        )
        self.pipeline.warmup(asr=False, diarizer=True)

        self._snapshot_load_s = time.perf_counter() - t0
        log.info(f"snapshot-load: diarizer ready in {self._snapshot_load_s:.1f}s")

    @modal.enter(snap=False)
    def move_to_gpu(self) -> None:
        """Post-restore hook: GPU is attached — move the diarizer onto it and
        build the Whisper model from the volume."""

        init_sentry("transcriber")
        log.info("post-restore: move_to_gpu() begin (GPU now attached)")
        cold_start_wall = time.time()

        t0 = time.perf_counter()
        self.pipeline.move_to_device()
        to_cuda_s = time.perf_counter() - t0

        t1 = time.perf_counter()
        self.pipeline.warmup(asr=True, diarizer=False)
        asr_load_s = time.perf_counter() - t1
        log.info(
            f"post-restore: diarizer→cuda {to_cuda_s * 1000:.0f}ms, "
            f"whisper {DEFAULT_MODEL} loaded in {asr_load_s:.1f}s"
        )

        # Built here (snap=False) so each container gets its own identity.
        self.runner = InferenceRunner(
            config="transcriber",
            gpu=GPU_NAME,
            scaledown_window_s=SCALEDOWN_WINDOW_S,
            log=log,
            cold={
                "snapshot_load": getattr(self, "_snapshot_load_s", 0.0),
                "to_cuda": to_cuda_s,
                "asr_load": asr_load_s,
            },
            cold_wall=(cold_start_wall, time.time()),
        )

    @modal.method()
    def generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        audio_bucket = payload["audio_bucket"]
        audio_key = payload["audio_key"]
        model = _validate_model(payload.get("model"))
        language = _validate_language(payload.get("language"))
        num_speakers = _validate_speakers(payload.get("num_speakers"))
        llm_cleanup = bool(payload.get("llm_cleanup"))

        with self.runner.start(payload) as run:
            log.info(
                f"[{run.request_id}] transcribe: start; key={audio_key} "
                f"model={model} language={language or 'auto'} "
                f"speakers={num_speakers or 'auto'} llm={llm_cleanup}"
            )
            run.tag("model", model)
            run.tag("llm_cleanup", llm_cleanup)

            with run.phase("download"):
                raw = download_from_s3(audio_bucket, audio_key)
                audio_path = _write_temp_audio(raw, audio_key)

            try:
                _guard_duration(probe_duration(audio_path), llm_cleanup)
                if llm_cleanup:
                    _guard_llm_weights()

                timer = StageTimer(run.request_id)
                try:
                    result = self.pipeline.run(
                        audio_path,
                        language=language,
                        model=model,
                        num_speakers=num_speakers,
                        llm_cleanup=llm_cleanup,
                        on_status=timer,
                    )
                finally:
                    timer.finish()

                # Recorded as phases after the fact: Grafana gets the stage
                # breakdown, Sentry gets the waterfall, and neither
                # double-counts against total_s.
                for key, started, ended in timer.intervals:
                    run.observe(key, ended - started)
                    run.retro_span(f"stage.{key}", started, ended)

                with run.phase("upload"):
                    urls = _upload_artifacts(result, audio_bucket)
            finally:
                _unlink_quietly(audio_path)

            run.batch(1)
            log.info(
                f"[{run.request_id}] transcribe: {len(result.segments)} segments, "
                f"{len(result.speakers)} speakers, {result.duration_s:.1f}s audio"
            )
            return run.finish(
                {
                    **urls,
                    "duration_s": round(result.duration_s, 2),
                    "language": result.language,
                    "model": model,
                    "speakers": result.speakers,
                    "segment_count": len(result.segments),
                    "llm_cleanup": llm_cleanup,
                    # Enough to render the page before the JSON is fetched.
                    "preview": to_payload(result.segments[:PREVIEW_SEGMENTS]),
                }
            )


def _write_temp_audio(raw: bytes, audio_key: str) -> str:
    """Persist the upload so ffmpeg/ffprobe can seek it. The extension is
    cosmetic — both sniff the container — but keeps logs readable."""

    _, _, tail = audio_key.rpartition(".")
    ext = tail.lower() if tail and len(tail) <= 5 else "bin"
    path = f"/tmp/{uuid.uuid4().hex}.{ext}"
    with open(path, "wb") as fh:
        fh.write(raw)
    return path


def _unlink_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _guard_duration(duration_s: float | None, llm_cleanup: bool) -> None:
    """Reject over-long audio before it burns GPU time. A None duration means
    ffprobe couldn't read the container; let it through and let the pipeline's
    own decode surface the real problem."""

    if duration_s is None:
        log.warning("could not probe duration; skipping the length guard")
        return

    if duration_s > MAX_AUDIO_SECONDS:
        raise ValueError(
            f"audio is {duration_s / 60:.1f} min; the limit is "
            f"{MAX_AUDIO_SECONDS // 60} min"
        )
    if llm_cleanup and duration_s > LLM_MAX_AUDIO_SECONDS:
        raise ValueError(
            f"LLM cleanup is limited to {LLM_MAX_AUDIO_SECONDS // 60} min of "
            f"audio; this file is {duration_s / 60:.1f} min. Retry with cleanup off."
        )


def _guard_llm_weights() -> None:
    """Fail fast instead of pulling ~15GB inside a request that would then blow
    the pipeline deadline."""

    if not llm.is_cached():
        raise RuntimeError(
            f"LLM cleanup requested but {llm.LLM_MODEL} is not on the volume. "
            "Run `python services/modal/transcriber/preload_llm.py` once, then "
            "retry."
        )


def _upload_artifacts(result: Any, bucket: str) -> dict[str, str]:
    """Render the three transcript formats and put them in S3.

    The JSON is the canonical artifact the SPA fetches; .txt and .srt are there
    so the page can offer real downloads instead of building files in the
    browser.
    """

    meta = {
        "language": result.language,
        "duration_s": round(result.duration_s, 2),
        "model": result.model_id,
        "speakers": result.speakers,
        "segment_count": len(result.segments),
    }
    return {
        "result_url": upload_to_s3(
            data_bytes=to_json(result.segments, meta).encode("utf-8"),
            bucket=bucket,
            folder="transcriber_results",
            extension="json",
        ),
        "txt_url": upload_to_s3(
            data_bytes=to_txt(result.segments).encode("utf-8"),
            bucket=bucket,
            folder="transcriber_results",
            extension="txt",
        ),
        "srt_url": upload_to_s3(
            data_bytes=to_srt(result.segments).encode("utf-8"),
            bucket=bucket,
            folder="transcriber_results",
            extension="srt",
        ),
    }
