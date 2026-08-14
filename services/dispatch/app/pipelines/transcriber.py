"""Uploaded audio → diarized transcript on Modal.

Dispatch only forwards the S3 location of the upload plus the requested
knobs; Modal downloads the audio, runs VAD → Whisper → pyannote, renders
.json/.txt/.srt and uploads all three back to S3 itself. Dispatch never
sees the audio or the transcript — it forwards the result URLs, so a long
transcript never travels through RabbitMQ or lands in Postgres.
"""

from __future__ import annotations

import logging
from typing import Any

from services.common.s3.client import S3Client

from .base import AsyncPipeline
from .modal_client import invoke_transcriber
from .schemas import TranscriberPipelineInput


log = logging.getLogger(__name__)

# Forwarded only when set, so the Modal app's own defaults stay the single
# source of truth for model/language/speaker-count behaviour.
_OPTIONAL_FIELDS = ("model", "language", "num_speakers")


class TranscriberPipeline(AsyncPipeline):
    def __init__(
        self,
        s3: S3Client,
        pipeline_input: TranscriberPipelineInput,
    ) -> None:
        # s3 is plumbed in by the service factory but unused — Modal owns
        # both the download and the uploads.
        self.s3 = s3
        self.pipeline_input = pipeline_input

    async def run(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "audio_bucket": self.pipeline_input.audio_bucket,
            "audio_key": self.pipeline_input.audio_key,
            "llm_cleanup": self.pipeline_input.llm_cleanup,
        }
        for field in _OPTIONAL_FIELDS:
            value = getattr(self.pipeline_input, field)
            if value is not None:
                payload[field] = value

        result = await invoke_transcriber(payload)

        result_url = result.get("result_url")
        if not result_url:
            raise RuntimeError(
                f"Modal transcriber endpoint returned no result_url; payload "
                f"keys: {list(result.keys())}"
            )

        log.info(
            f"Dispatched transcriber complete; "
            f"{result.get('segment_count', 0)} segments, "
            f"{len(result.get('speakers') or [])} speakers, "
            f"transcript at {result_url}"
        )
        return {
            "result_url": result_url,
            "txt_url": result.get("txt_url"),
            "srt_url": result.get("srt_url"),
            "duration_s": result.get("duration_s"),
            "language": result.get("language"),
            "model": result.get("model"),
            "speakers": result.get("speakers") or [],
            "segment_count": result.get("segment_count", 0),
            "llm_cleanup": bool(result.get("llm_cleanup")),
            "preview": result.get("preview") or [],
        }
