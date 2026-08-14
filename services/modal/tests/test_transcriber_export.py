"""Rendering contracts. The JSON shape in particular is read by the SPA
(services/web/src/components/transcriber/useTranscript.ts), so it is a real
interface rather than an implementation detail."""

from __future__ import annotations

import json

from transcriber_pipeline.export import to_json, to_payload, to_srt, to_txt
from transcriber_pipeline.postprocess import build_prompt, is_plausible


SEGMENTS = [
    {
        "start": 0.0,
        "end": 5.25,
        "speaker": "SPEAKER_00",
        "text": "Hello there",
        "words": [{"start": 0.0, "end": 1.0, "text": "Hello"}],
    },
    {
        "start": 61.5,
        "end": 65.0,
        "speaker": "SPEAKER_01",
        "text": "Hi",
        "words": [],
    },
]


def test_txt_carries_speaker_and_mmss_timestamps():
    out = to_txt(SEGMENTS)

    assert "[00:00 - 00:05] SPEAKER_00" in out
    assert "[01:01 - 01:05] SPEAKER_01" in out


def test_srt_is_numbered_and_uses_comma_milliseconds():
    out = to_srt(SEGMENTS)

    assert out.startswith("1\n00:00:00,000 --> 00:00:05,250")
    assert "2\n00:01:01,500 --> 00:01:05,000" in out
    assert out.endswith("\n")


def test_payload_drops_word_timings():
    assert all("words" not in seg for seg in to_payload(SEGMENTS))


def test_payload_keeps_the_rendered_fields():
    assert to_payload(SEGMENTS)[0] == {
        "start": 0.0,
        "end": 5.25,
        "speaker": "SPEAKER_00",
        "text": "Hello there",
    }


def test_json_wraps_segments_with_meta():
    parsed = json.loads(to_json(SEGMENTS, {"language": "en", "duration_s": 65.0}))

    assert parsed["meta"] == {"language": "en", "duration_s": 65.0}
    assert len(parsed["segments"]) == 2


def test_json_keeps_non_ascii_readable():
    assert "Привет" in to_json([{**SEGMENTS[0], "text": "Привет"}])


def test_json_without_meta_still_has_the_key():
    # The SPA reads doc.meta unconditionally.
    assert json.loads(to_json(SEGMENTS))["meta"] == {}


# ----------------------------- cleanup guards ------------------------------ #


def test_cleanup_keeps_output_of_a_similar_length():
    assert is_plausible("hello there", "Hello, there.")


def test_cleanup_rejects_a_truncated_answer():
    assert not is_plausible("a fairly long segment of speech", "ok")


def test_cleanup_rejects_a_rambling_answer():
    assert not is_plausible("short", "short " * 20)


def test_cleanup_prompt_includes_glossary_and_context():
    prompt = build_prompt(
        "raw text", glossary="ACME Corp", prev_context="previous words"
    )

    assert "ACME Corp" in prompt
    assert "previous words" in prompt
    assert prompt.rstrip().endswith("raw text")


def test_cleanup_prompt_omits_empty_sections():
    prompt = build_prompt("raw text")

    assert "Glossary" not in prompt
    assert "Previous context" not in prompt


# ------------------------------ media probing ------------------------------ #
#
# The ffmpeg/ffprobe calls themselves need real files, but parsing ffprobe's
# key=value output is where a silent wrong answer would come from: a missing
# audio stream read as "present" means a failed extraction instead of a clear
# message.


def _parse(monkeypatch, stdout: str) -> dict:
    from transcriber_pipeline import media

    class FakeProc:
        def __init__(self, out: bytes) -> None:
            self.stdout = out

    monkeypatch.setattr(media, "_run", lambda cmd, what: FakeProc(stdout.encode()))
    return media.probe_media("whatever.mov")


def test_probe_reads_duration_and_both_stream_kinds(monkeypatch):
    facts = _parse(
        monkeypatch, "codec_type=video\ncodec_type=audio\nduration=612.500000\n"
    )

    assert facts["duration_s"] == 612.5
    assert facts["has_audio"] is True
    assert facts["has_video"] is True


def test_probe_reports_a_silent_video(monkeypatch):
    facts = _parse(monkeypatch, "codec_type=video\nduration=30.0\n")

    assert facts["has_video"] is True
    assert facts["has_audio"] is False


def test_probe_reports_an_audio_only_file(monkeypatch):
    facts = _parse(monkeypatch, "codec_type=audio\nduration=30.0\n")

    assert facts["has_audio"] is True
    assert facts["has_video"] is False


def test_probe_survives_a_missing_duration(monkeypatch):
    # A stream copy or a live capture can carry no container duration.
    facts = _parse(monkeypatch, "codec_type=audio\nduration=N/A\n")

    assert facts["duration_s"] is None
    assert facts["has_audio"] is True


def test_probe_handles_several_audio_streams(monkeypatch):
    facts = _parse(
        monkeypatch,
        "codec_type=video\ncodec_type=audio\ncodec_type=audio\nduration=10.0\n",
    )

    assert facts["streams"].count("audio") == 2
