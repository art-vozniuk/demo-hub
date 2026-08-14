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
