"""Uploaded audio or video → diarized transcript on Modal.

Video goes through an extra step first: a CPU container demuxes it to 16 kHz
mono FLAC and puts that back in S3, and only the extracted audio reaches the
GPU. A 90-minute video is gigabytes of frames wrapped around a few dozen
megabytes of speech, and downloading all of it onto a GPU container that will
throw the frames away is the expensive way to do nothing.

Either way dispatch only forwards S3 locations: Modal downloads, transcribes,
renders .json/.txt/.srt and uploads them itself, so a long transcript never
travels through RabbitMQ or lands in Postgres.
"""

from __future__ import annotations

import logging
from typing import Any

from services.common.constants import has_video_extension
from services.common.s3.client import S3Client

from .base import AsyncPipeline
from .modal_client import invoke_transcriber, invoke_transcriber_extract
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

    def needs_extraction(self) -> bool:
        """Whether to run the demux step first.

        The client says what it picked (`source_kind`); the key's extension is
        the fallback when it didn't. Guessing wrong is cheap in both
        directions — the transcription pipeline decodes video containers fine,
        and extracting an audio-only file still yields correct audio — so an
        extension is a good enough signal.
        """

        if self.pipeline_input.source_kind == "video":
            return True
        if self.pipeline_input.source_kind == "audio":
            return False
        return has_video_extension(self.pipeline_input.audio_key)

    async def run(self) -> dict[str, Any]:
        bucket = self.pipeline_input.audio_bucket
        key = self.pipeline_input.audio_key
        extracted_audio_url: str | None = None

        if self.needs_extraction():
            extraction = await invoke_transcriber_extract(
                {
                    "audio_bucket": bucket,
                    "audio_key": key,
                    # Lets the extractor apply the same length ceiling the
                    # transcription step would, before doing the work.
                    "llm_cleanup": self.pipeline_input.llm_cleanup,
                }
            )
            extracted_key = extraction.get("audio_key")
            if not extracted_key:
                raise RuntimeError(
                    "Modal transcriber extraction returned no audio_key; "
                    f"payload keys: {list(extraction.keys())}"
                )
            log.info(
                f"Extracted audio from {key}: "
                f"{extraction.get('source_size_bytes')} -> "
                f"{extraction.get('audio_size_bytes')} bytes, "
                f"{extraction.get('duration_s')}s"
            )
            bucket = extraction.get("audio_bucket") or bucket
            key = extracted_key
            extracted_audio_url = extraction.get("audio_url")

        payload: dict[str, Any] = {
            "audio_bucket": bucket,
            "audio_key": key,
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
            # Present only for video: the audio the transcript was made from,
            # so the result page can play it without the video.
            "extracted_audio_url": extracted_audio_url,
        }
