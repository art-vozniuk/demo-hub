"""Modal app: audio or video → diarized transcript on a cheap GPU.

Two classes, both endpoint-less and invoked by name through the gateway:

- `AudioExtractor` (CPU): demuxes a video upload to 16 kHz mono FLAC. A
  90-minute recording is gigabytes of frames around a few dozen megabytes of
  speech, and none of that should touch a GPU container — so dispatch runs this
  first for video and hands the GPU the extracted audio.
- `TranscriberInference` (GPU): Silero VAD → faster-whisper (CTranslate2,
  float16) per speech chunk → hallucination filter → pyannote speaker turns →
  word-level speaker assignment → segment merge, with optional LLM cleanup.

The pipeline itself lives in services/modal/transcriber_pipeline and ships into
the image as a local source package.

The container owns the whole job: download the upload from S3, run the
pipeline, render .json/.txt/.srt and upload all three back to S3. Dispatch only
forwards the URLs, so a long transcript never travels through RabbitMQ or lands
in Postgres.

Deploy / preload via services/modal/transcriber/{deploy,preload,preload_llm}.py.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import modal

from common.constants import MODAL_LONG_FUNCTION_TIMEOUT_SECONDS
from common.instrument import InferenceRunner
from common.lib import (
    MODEL_DIR,
    configure_logging,
    download_from_s3,
    download_from_s3_to_file,
    make_app,
    upload_to_s3,
    upload_to_s3_with_key,
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

# Both classes run to MODAL_LONG_FUNCTION_TIMEOUT_SECONDS (1800s), matched by
# the deadline dispatch polls to. Warm throughput on an L4 is roughly 8-15x
# realtime end to end, so 90 minutes of audio is ~6-11 minutes on turbo and
# ~15-20 on large-v3 — inside the budget, with the cold start on top.
MAX_AUDIO_SECONDS = 90 * 60
# Cleanup is one LLM generation per segment, which dominates the run; hold it to
# a much shorter ceiling rather than letting it eat the whole deadline.
LLM_MAX_AUDIO_SECONDS = 15 * 60

# Segments inlined in the response so the UI can render immediately; the rest
# comes from the JSON in S3.
PREVIEW_SEGMENTS = 20


log = configure_logging("transcriber")

# Named, because the smoke test resolves the deployed classes by app name the
# same way the gateway's ROUTES do.
APP_NAME = "demo-hub-transcriber"

app, volume = make_app(APP_NAME, "transcriber-models")


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
        # pyannote.audio 3.3.2 only floors its own ecosystem (`pyannote.core
        # >=5`, `pyannote.metrics >=3.2`, ...), so an unbounded install picks up
        # the 4.x/6.x majors released after it — which is how the diarizer ended
        # up being handed a `token=` kwarg it never accepted. Cap each at the
        # major it was released against.
        "pyannote.core<6",
        "pyannote.database<6",
        "pyannote.metrics<4",
        "pyannote.pipeline<4",
        # Imported at module scope by pyannote.audio's *training* code, which
        # `pyannote.audio.pipelines` pulls in transitively — undeclared, and
        # pyannote.metrics 4.x stopped bringing it in as a side effect.
        "matplotlib>=3.7",
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
    from transcriber_pipeline.media import (
        EXTRACT_EXTENSION,
        NoAudioStreamError,
        extract_audio,
        probe_media,
    )
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


SMOKE_SAMPLE_URLS: tuple[str, ...] = (
    # ~11s of JFK ("ask not what your country can do for you") and ~20s of a
    # physics lecture — two different voices, from two long-lived files in
    # faster-whisper's own test data, so diarization has something real to
    # separate rather than one speaker talking to themselves.
    "https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/tests/data/jfk.flac",
    "https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/tests/data/physicsworks.wav",
)

# Each sample is trimmed to this before being joined, to keep a smoke run
# cheap while leaving both voices long enough to be told apart.
SMOKE_CLIP_SECONDS = 15

# A phrase the first sample definitely contains; the check that the transcript
# is a transcript rather than plausible-looking noise.
SMOKE_EXPECTED_PHRASE = "country"


def _gateway_payload(route: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The payload as the gateway hands it over, not as it is nicer to write.

    dispatch calls the gateway, which routes on payload["model"] and overwrites
    it with its own route key before spawning this app. A smoke test that
    invokes `generate` with a hand-made dict is free to put anything in `model`
    — and one that put the Whisper size there passed while production raised
    `unsupported model 'transcriber'` on every request. So shape it the way the
    gateway does, route key included.
    """

    return {**payload, "model": route, "spawned_at": time.time()}


@app.function(
    image=transcriber_image,
    volumes={MODEL_DIR: volume},
    timeout=MODAL_LONG_FUNCTION_TIMEOUT_SECONDS,
    cpu=2.0,
    memory=4096,
    secrets=[
        modal.Secret.from_name("supabase-s3"),
        modal.Secret.from_name("huggingface"),
        modal.Secret.from_name("sentry"),
    ],
)
def smoke_test(
    source: str = "audio",
    model: str = "medium",
    bucket: str = "media",
    target: str = "source",
) -> dict[str, Any]:
    """End-to-end check of the real classes against a real recording.

    Builds a two-speaker sample from public test audio, puts it in S3, and runs
    exactly what dispatch runs — `AudioExtractor` first when `source` is video,
    then `TranscriberInference` — asserting the transcript actually contains
    speech from the sample. Run it with
    `modal run services/modal/transcriber/app.py::smoke_test`, or through the
    smoke-transcriber workflow.

    `target` picks which copy of those classes runs. "source" uses the ones in
    this file, so the check covers the branch you are on. "deployed" resolves
    them by name, exactly as the gateway does, which is the only way to exercise
    what production does at container start-up: `modal run` builds an ephemeral
    app, and Modal disables memory snapshots for those — so the snapshot hooks,
    where a broken diarizer load actually killed production, never execute.
    """

    import subprocess
    import urllib.request

    if source not in ("audio", "video"):
        raise ValueError(f"source must be 'audio' or 'video', got {source!r}")
    if target not in ("source", "deployed"):
        raise ValueError(f"target must be 'source' or 'deployed', got {target!r}")

    if target == "deployed":
        extractor_cls = modal.Cls.from_name(APP_NAME, "AudioExtractor")
        inference_cls = modal.Cls.from_name(APP_NAME, "TranscriberInference")
    else:
        extractor_cls, inference_cls = AudioExtractor, TranscriberInference

    work = f"/tmp/smoke-{uuid.uuid4().hex}"
    os.makedirs(work, exist_ok=True)

    clips: list[str] = []
    for index, url in enumerate(SMOKE_SAMPLE_URLS):
        raw_path = f"{work}/raw-{index}{_extension_suffix(url)}"
        log.info(f"smoke: downloading {url}")
        urllib.request.urlretrieve(url, raw_path)
        clip = f"{work}/clip-{index}.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-t",
                str(SMOKE_CLIP_SECONDS),
                "-i",
                raw_path,
                "-ac",
                "1",
                "-ar",
                "16000",
                clip,
            ],
            check=True,
        )
        clips.append(clip)

    joined = f"{work}/joined.flac"
    concat_list = f"{work}/concat.txt"
    with open(concat_list, "w") as fh:
        fh.writelines(f"file '{clip}'\n" for clip in clips)
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_list,
            "-ac",
            "1",
            "-ar",
            "16000",
            joined,
        ],
        check=True,
    )

    upload_path, extension = joined, "flac"
    if source == "video":
        # A black 5fps track around the audio: enough to make this a real video
        # container for the extractor to demux.
        upload_path = f"{work}/joined.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=320x240:r=5",
                "-i",
                joined,
                "-shortest",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                upload_path,
            ],
            check=True,
        )
        extension = "mp4"

    size_mb = os.path.getsize(upload_path) / (1024 * 1024)
    log.info(f"smoke: uploading {size_mb:.2f} MB {extension} sample")
    with open(upload_path, "rb") as fh:
        key, url = upload_to_s3_with_key(
            data_bytes=fh.read(),
            bucket=bucket,
            folder="transcriber_smoke",
            extension=extension,
        )

    payload: dict[str, Any] = {"audio_bucket": bucket, "audio_key": key}
    extraction: dict[str, Any] | None = None
    if source == "video":
        log.info(f"smoke: running {target} AudioExtractor")
        extraction = extractor_cls().generate.remote(
            _gateway_payload("transcriber_extract", payload)
        )
        payload = {
            "audio_bucket": extraction["audio_bucket"],
            "audio_key": extraction["audio_key"],
        }

    log.info(
        f"smoke: running {target} TranscriberInference on {payload['audio_key']}"
    )
    result = inference_cls().generate.remote(
        _gateway_payload("transcriber", {**payload, "whisper_model": model})
    )

    transcript = " ".join(seg["text"] for seg in result.get("preview", []))
    log.info(f"smoke: transcript -> {transcript}")
    log.info(
        f"smoke: {result.get('segment_count')} segments, "
        f"speakers={result.get('speakers')}, language={result.get('language')}, "
        f"duration={result.get('duration_s')}s"
    )

    problems: list[str] = []
    if not result.get("segment_count"):
        problems.append("no segments were produced")
    if not result.get("speakers"):
        problems.append("no speakers were assigned")
    if SMOKE_EXPECTED_PHRASE not in transcript.lower():
        problems.append(
            f"transcript does not contain {SMOKE_EXPECTED_PHRASE!r}: {transcript!r}"
        )
    if problems:
        raise RuntimeError("smoke test failed: " + "; ".join(problems))

    log.info("smoke: OK")
    return {
        "source": source,
        "target": target,
        "model": model,
        "source_url": url,
        "extraction": extraction,
        "segment_count": result.get("segment_count"),
        "speakers": result.get("speakers"),
        "language": result.get("language"),
        "duration_s": result.get("duration_s"),
        "result_url": result.get("result_url"),
        "transcript": transcript,
    }


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
    # No GPU: this is ffmpeg demuxing, bounded by download and disk. Generous
    # CPU because ffmpeg threads well; generous ephemeral memory is not needed
    # because both the source and the output are streamed through files.
    cpu=4.0,
    memory=4096,
    scaledown_window=SCALEDOWN_WINDOW_S,
    timeout=MODAL_LONG_FUNCTION_TIMEOUT_SECONDS,
    secrets=[
        modal.Secret.from_name("supabase-s3"),
        modal.Secret.from_name("sentry"),
    ],
)
@modal.concurrent(max_inputs=1)
class AudioExtractor:
    """Video in S3 → 16 kHz mono FLAC in S3.

    Runs before the GPU class for video uploads so the transcription container
    never downloads gigabytes of frames it would immediately throw away. The
    length guard lives here too: rejecting an over-long recording before
    extraction saves the extraction as well as the transcription.
    """

    @modal.enter()
    def setup(self) -> None:
        init_sentry("transcriber-extract")
        self.runner = InferenceRunner(
            config="transcriber_extract",
            # Not a GPU workload; the label keeps the metric series honest
            # rather than attributing CPU seconds to a GPU.
            gpu="cpu",
            scaledown_window_s=SCALEDOWN_WINDOW_S,
            log=log,
        )

    @modal.method()
    def generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        source_bucket = payload["audio_bucket"]
        source_key = payload["audio_key"]
        # Forwarded so the length guard below applies the same ceiling the
        # transcription step would — rejecting here saves the extraction too.
        llm_cleanup = bool(payload.get("llm_cleanup"))

        with self.runner.start(payload) as run:
            log.info(f"[{run.request_id}] extract: start; key={source_key}")
            source_path = f"/tmp/{uuid.uuid4().hex}{_extension_suffix(source_key)}"
            dest_path = f"/tmp/{uuid.uuid4().hex}.{EXTRACT_EXTENSION}"

            try:
                with run.phase("download"):
                    source_bytes = download_from_s3_to_file(
                        source_bucket, source_key, source_path
                    )
                log.info(
                    f"[{run.request_id}] downloaded "
                    f"{source_bytes / (1024 * 1024):.1f} MB"
                )

                with run.phase("probe"):
                    facts = probe_media(source_path)
                if not facts["has_audio"]:
                    raise NoAudioStreamError(
                        "This file has no audio track, so there is nothing to "
                        "transcribe."
                    )
                duration_s = facts["duration_s"]
                _guard_duration(duration_s, llm_cleanup)

                with run.phase("extract"):
                    extract_audio(source_path, dest_path)

                audio_bytes = os.path.getsize(dest_path)
                with run.phase("upload"):
                    with open(dest_path, "rb") as fh:
                        audio_key, audio_url = upload_to_s3_with_key(
                            data_bytes=fh.read(),
                            bucket=source_bucket,
                            folder="transcriber_audio",
                            extension=EXTRACT_EXTENSION,
                        )
            finally:
                _unlink_quietly(source_path)
                _unlink_quietly(dest_path)

            log.info(
                f"[{run.request_id}] extract: done; "
                f"{source_bytes / (1024 * 1024):.1f} MB -> "
                f"{audio_bytes / (1024 * 1024):.1f} MB"
            )
            run.batch(1)
            return run.finish(
                {
                    # Same shape the transcription step takes as input, so
                    # dispatch can hand this straight on.
                    "audio_bucket": source_bucket,
                    "audio_key": audio_key,
                    "audio_url": audio_url,
                    "duration_s": round(duration_s, 2) if duration_s else None,
                    "source_size_bytes": source_bytes,
                    "audio_size_bytes": audio_bytes,
                    "had_video": bool(facts["has_video"]),
                }
            )


@app.cls(
    image=transcriber_image,
    gpu=GPU_NAME,
    volumes={MODEL_DIR: volume},
    scaledown_window=SCALEDOWN_WINDOW_S,
    timeout=MODAL_LONG_FUNCTION_TIMEOUT_SECONDS,
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
        # `whisper_model`, not `model`: the gateway routes on payload["model"]
        # and overwrites it with its own route key ("transcriber") on the way
        # in, so a Whisper size put there never reaches this container.
        model = _validate_model(payload.get("whisper_model"))
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


def _extension_suffix(key: str) -> str:
    """`.mov` for an S3 key ending in one, `.bin` otherwise. Cosmetic — ffmpeg
    and ffprobe sniff the container — but it keeps logs and errors readable."""

    _, _, tail = key.rpartition(".")
    return f".{tail.lower()}" if tail and len(tail) <= 5 else ".bin"


def _write_temp_audio(raw: bytes, audio_key: str) -> str:
    """Persist the upload so ffmpeg/ffprobe can seek it."""

    path = f"/tmp/{uuid.uuid4().hex}{_extension_suffix(audio_key)}"
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
