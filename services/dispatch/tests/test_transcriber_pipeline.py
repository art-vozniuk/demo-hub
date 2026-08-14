"""What the transcriber pipeline puts on the wire and what it hands back.

Both directions are contracts with something outside this module: the payload
shape is read by services/modal/transcriber/app.py, and the returned dict is
what the SPA renders out of `pipelines.result`.
"""

import pytest

from services.dispatch.app.pipelines.schemas import TranscriberPipelineInput
from services.dispatch.app.pipelines.transcriber import TranscriberPipeline


MODAL_RESULT = {
    "result_url": "https://s3.example/transcriber_results/a.json",
    "txt_url": "https://s3.example/transcriber_results/b.txt",
    "srt_url": "https://s3.example/transcriber_results/c.srt",
    "duration_s": 612.5,
    "language": "ru",
    "model": "large-v3-turbo",
    "speakers": ["SPEAKER_00", "SPEAKER_01"],
    "segment_count": 87,
    "llm_cleanup": False,
    "preview": [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00", "text": "hi"}],
}


EXTRACT_RESULT = {
    "audio_bucket": "media",
    "audio_key": "transcriber_audio/extracted.flac",
    "audio_url": "https://s3.example/transcriber_audio/extracted.flac",
    "duration_s": 612.5,
    "source_size_bytes": 1_500_000_000,
    "audio_size_bytes": 90_000_000,
    "had_video": True,
}


@pytest.fixture
def captured_payload(mocker):
    """Patch the Modal call and expose the payload it was handed."""

    captured: dict = {}

    async def fake_invoke(payload):
        captured.update(payload)
        return dict(MODAL_RESULT)

    mocker.patch(
        "services.dispatch.app.pipelines.transcriber.invoke_transcriber",
        side_effect=fake_invoke,
    )
    return captured


@pytest.fixture
def captured_extract(mocker):
    """Patch the extraction call and expose the payload it was handed."""

    captured: dict = {}

    async def fake_extract(payload):
        captured.update(payload)
        return dict(EXTRACT_RESULT)

    mocker.patch(
        "services.dispatch.app.pipelines.transcriber.invoke_transcriber_extract",
        side_effect=fake_extract,
    )
    return captured


def build(mock_s3_client, **overrides) -> TranscriberPipeline:
    return TranscriberPipeline(
        s3=mock_s3_client,
        pipeline_input=TranscriberPipelineInput(
            audio_bucket="media",
            audio_key="user/meeting.m4a",
            **overrides,
        ),
    )


async def test_payload_carries_the_audio_location(mock_s3_client, captured_payload):
    await build(mock_s3_client).run()

    assert captured_payload["audio_bucket"] == "media"
    assert captured_payload["audio_key"] == "user/meeting.m4a"


async def test_unset_knobs_are_omitted_so_modal_defaults_apply(
    mock_s3_client, captured_payload
):
    await build(mock_s3_client).run()

    assert "model" not in captured_payload
    assert "language" not in captured_payload
    assert "num_speakers" not in captured_payload


async def test_llm_cleanup_is_always_sent_explicitly(mock_s3_client, captured_payload):
    # A bool has no "unset" state worth deferring: send it either way so the
    # container never has to guess which side the default came from.
    await build(mock_s3_client).run()

    assert captured_payload["llm_cleanup"] is False


async def test_set_knobs_are_forwarded(mock_s3_client, captured_payload):
    await build(
        mock_s3_client,
        model="large-v3",
        language="en",
        num_speakers=4,
        llm_cleanup=True,
    ).run()

    assert captured_payload["model"] == "large-v3"
    assert captured_payload["language"] == "en"
    assert captured_payload["num_speakers"] == 4
    assert captured_payload["llm_cleanup"] is True


async def test_result_forwards_urls_and_metadata(mock_s3_client, captured_payload):
    result = await build(mock_s3_client).run()

    assert result["result_url"] == MODAL_RESULT["result_url"]
    assert result["txt_url"] == MODAL_RESULT["txt_url"]
    assert result["srt_url"] == MODAL_RESULT["srt_url"]
    assert result["language"] == "ru"
    assert result["duration_s"] == 612.5
    assert result["speakers"] == ["SPEAKER_00", "SPEAKER_01"]
    assert result["segment_count"] == 87
    assert result["preview"] == MODAL_RESULT["preview"]


async def test_missing_lists_become_empty_not_none(mock_s3_client, mocker):
    async def fake_invoke(payload):
        return {"result_url": "https://s3.example/a.json"}

    mocker.patch(
        "services.dispatch.app.pipelines.transcriber.invoke_transcriber",
        side_effect=fake_invoke,
    )

    result = await build(mock_s3_client).run()

    # The SPA maps over both; None would crash the page.
    assert result["speakers"] == []
    assert result["preview"] == []
    assert result["segment_count"] == 0


async def test_a_result_without_a_url_fails_loudly(mock_s3_client, mocker):
    async def fake_invoke(payload):
        return {"segment_count": 0}

    mocker.patch(
        "services.dispatch.app.pipelines.transcriber.invoke_transcriber",
        side_effect=fake_invoke,
    )

    with pytest.raises(RuntimeError, match="no result_url"):
        await build(mock_s3_client).run()


# --------------------------- video → extract first -------------------------- #


class TestNeedsExtraction:
    def test_an_explicit_video_kind_wins(self, mock_s3_client):
        pipeline = build(mock_s3_client, source_kind="video")

        assert pipeline.needs_extraction() is True

    def test_an_explicit_audio_kind_skips_it_even_for_a_video_key(self, mock_s3_client):
        # The client knows what it picked; trust it over the extension.
        pipeline = TranscriberPipeline(
            s3=mock_s3_client,
            pipeline_input=TranscriberPipelineInput(
                audio_bucket="media",
                audio_key="user/clip.mov",
                source_kind="audio",
            ),
        )

        assert pipeline.needs_extraction() is False

    @pytest.mark.parametrize("key", ["user/a.mov", "user/a.MOV", "user/a.mp4"])
    def test_a_video_extension_triggers_it_without_a_hint(self, mock_s3_client, key):
        pipeline = TranscriberPipeline(
            s3=mock_s3_client,
            pipeline_input=TranscriberPipelineInput(
                audio_bucket="media", audio_key=key
            ),
        )

        assert pipeline.needs_extraction() is True

    @pytest.mark.parametrize("key", ["user/a.mp3", "user/a.m4a", "user/noext"])
    def test_audio_keys_skip_it(self, mock_s3_client, key):
        pipeline = TranscriberPipeline(
            s3=mock_s3_client,
            pipeline_input=TranscriberPipelineInput(
                audio_bucket="media", audio_key=key
            ),
        )

        assert pipeline.needs_extraction() is False


async def test_audio_never_calls_the_extractor(mock_s3_client, mocker):
    extract = mocker.patch(
        "services.dispatch.app.pipelines.transcriber.invoke_transcriber_extract"
    )
    mocker.patch(
        "services.dispatch.app.pipelines.transcriber.invoke_transcriber",
        return_value=dict(MODAL_RESULT),
    )

    await build(mock_s3_client).run()

    extract.assert_not_called()


async def test_video_transcribes_the_extracted_audio_not_the_upload(
    mock_s3_client, captured_payload, captured_extract
):
    await build(mock_s3_client, source_kind="video").run()

    assert captured_extract["audio_key"] == "user/meeting.m4a"
    # The GPU step must be handed the extracted track, never the video.
    assert captured_payload["audio_key"] == EXTRACT_RESULT["audio_key"]
    assert captured_payload["audio_bucket"] == EXTRACT_RESULT["audio_bucket"]


async def test_extraction_is_told_about_cleanup_so_it_can_reject_early(
    mock_s3_client, captured_payload, captured_extract
):
    await build(mock_s3_client, source_kind="video", llm_cleanup=True).run()

    assert captured_extract["llm_cleanup"] is True


async def test_video_result_exposes_the_extracted_audio(
    mock_s3_client, captured_payload, captured_extract
):
    result = await build(mock_s3_client, source_kind="video").run()

    assert result["extracted_audio_url"] == EXTRACT_RESULT["audio_url"]


async def test_audio_result_has_no_extracted_url(mock_s3_client, captured_payload):
    result = await build(mock_s3_client).run()

    assert result["extracted_audio_url"] is None


async def test_extraction_without_a_key_fails_loudly(mock_s3_client, mocker):
    mocker.patch(
        "services.dispatch.app.pipelines.transcriber.invoke_transcriber_extract",
        return_value={"duration_s": 1.0},
    )

    with pytest.raises(RuntimeError, match="no audio_key"):
        await build(mock_s3_client, source_kind="video").run()


async def test_a_failed_extraction_never_reaches_the_gpu(mock_s3_client, mocker):
    transcribe = mocker.patch(
        "services.dispatch.app.pipelines.transcriber.invoke_transcriber"
    )
    mocker.patch(
        "services.dispatch.app.pipelines.transcriber.invoke_transcriber_extract",
        side_effect=RuntimeError("this file has no audio track"),
    )

    with pytest.raises(RuntimeError, match="no audio track"):
        await build(mock_s3_client, source_kind="video").run()
    transcribe.assert_not_called()
