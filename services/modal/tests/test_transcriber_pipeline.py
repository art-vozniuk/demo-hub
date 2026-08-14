"""Pure-logic coverage for the vendored transcriber pipeline.

These are the stages the CUDA port had to preserve from the original Mac
pipeline — hallucination filtering, VAD chunking, speaker assignment and
flicker smoothing, segment merging — so they are worth pinning without a model,
a GPU or a network.
"""

from __future__ import annotations

import numpy as np
import pytest

from transcriber_pipeline.asr import (
    WHISPER_REPOS,
    AsrSegment,
    AsrWord,
    resolve_model,
)
from transcriber_pipeline.pipeline import TranscriptionPipeline, _overlap
from transcriber_pipeline.vad import SpeechRegion


def seg(
    start: float,
    end: float,
    text: str = "hello",
    *,
    no_speech_prob: float = 0.0,
    compression_ratio: float = 1.0,
    avg_logprob: float = -0.2,
    words: list[AsrWord] | None = None,
) -> AsrSegment:
    return AsrSegment(
        start=start,
        end=end,
        text=text,
        words=words if words is not None else [AsrWord(start, end, text)],
        no_speech_prob=no_speech_prob,
        compression_ratio=compression_ratio,
        avg_logprob=avg_logprob,
    )


# ------------------------------ model aliases ------------------------------ #


@pytest.mark.parametrize("alias", sorted(WHISPER_REPOS))
def test_every_alias_resolves_to_a_repo_id(alias):
    assert "/" in resolve_model(alias)


def test_explicit_repo_id_passes_through():
    assert resolve_model("acme/whisper-x") == "acme/whisper-x"


def test_unknown_alias_falls_back_to_large_v3():
    assert resolve_model("nonsense") == resolve_model("large-v3")


# --------------------------------- geometry -------------------------------- #


def test_overlap_disjoint_intervals_is_zero():
    assert _overlap(0.0, 1.0, 2.0, 3.0) == 0.0


def test_overlap_partial():
    assert _overlap(0.0, 2.0, 1.0, 3.0) == pytest.approx(1.0)


def test_shifted_moves_segment_and_its_words():
    moved = seg(1.0, 2.0).shifted(10.0)

    assert (moved.start, moved.end) == (11.0, 12.0)
    assert (moved.words[0].start, moved.words[0].end) == (11.0, 12.0)


def test_shifted_leaves_the_original_untouched():
    original = seg(1.0, 2.0)
    original.shifted(5.0)

    assert (original.start, original.words[0].start) == (1.0, 1.0)


# --------------------------- hallucination filter -------------------------- #


class TestHallucinationFilter:
    def test_keeps_a_healthy_segment(self):
        assert TranscriptionPipeline.filter_hallucinations([seg(0, 1)])

    def test_drops_silence(self):
        assert (
            TranscriptionPipeline.filter_hallucinations([seg(0, 1, no_speech_prob=0.7)])
            == []
        )

    def test_drops_repetition_loops(self):
        assert (
            TranscriptionPipeline.filter_hallucinations(
                [seg(0, 1, compression_ratio=2.5)]
            )
            == []
        )

    def test_drops_low_confidence(self):
        assert (
            TranscriptionPipeline.filter_hallucinations([seg(0, 1, avg_logprob=-1.5)])
            == []
        )

    def test_drops_whitespace_only_text(self):
        assert TranscriptionPipeline.filter_hallucinations([seg(0, 1, "   ")]) == []


# ------------------------------- VAD chunking ------------------------------ #


class TestVadRegionMerging:
    def test_merges_regions_closer_than_the_gap(self):
        merged = TranscriptionPipeline.merge_vad_regions(
            [SpeechRegion(0.0, 1.0), SpeechRegion(1.1, 2.0)]
        )

        assert merged == [SpeechRegion(0.0, 2.0)]

    def test_keeps_regions_separated_by_a_real_pause(self):
        regions = [SpeechRegion(0.0, 1.0), SpeechRegion(3.0, 4.0)]

        assert TranscriptionPipeline.merge_vad_regions(regions) == regions

    def test_empty_input(self):
        assert TranscriptionPipeline.merge_vad_regions([]) == []


# --------------------------- speaker assignment ---------------------------- #


def words(*spec: tuple[float, float, str]) -> list[AsrWord]:
    return [AsrWord(start, end, text) for start, end, text in spec]


class TestAssignSpeakers:
    def test_word_takes_the_speaker_it_overlaps_most(self):
        labeled = TranscriptionPipeline.assign_speakers(
            [seg(0, 2, words=words((0.0, 1.0, "one"), (1.0, 2.0, "two")))],
            [(0.0, 1.2, "SPEAKER_00"), (1.2, 3.0, "SPEAKER_01")],
        )

        assert [w["speaker"] for w in labeled] == ["SPEAKER_00", "SPEAKER_01"]

    def test_word_with_no_overlap_falls_back_to_the_first_speaker(self):
        labeled = TranscriptionPipeline.assign_speakers(
            [seg(0, 1, words=words((0.0, 1.0, "one")))],
            [(50.0, 60.0, "SPEAKER_07")],
        )

        assert labeled[0]["speaker"] == "SPEAKER_00"

    def test_blank_words_are_dropped(self):
        labeled = TranscriptionPipeline.assign_speakers(
            [seg(0, 2, words=words((0.0, 1.0, "  "), (1.0, 2.0, "kept")))],
            [(0.0, 2.0, "SPEAKER_00")],
        )

        assert [w["text"] for w in labeled] == ["kept"]

    def test_a_single_flickered_word_is_reassigned_to_its_neighbours(self):
        labeled = TranscriptionPipeline.assign_speakers(
            [
                seg(
                    0,
                    3,
                    words=words((0.0, 1.0, "a"), (1.0, 2.0, "b"), (2.0, 3.0, "c")),
                )
            ],
            [
                (0.0, 1.0, "SPEAKER_00"),
                (1.0, 2.0, "SPEAKER_01"),
                (2.0, 3.0, "SPEAKER_00"),
            ],
        )

        assert [w["speaker"] for w in labeled] == ["SPEAKER_00"] * 3

    def test_a_long_run_is_left_alone(self):
        # Three words is past FLICKER_RUN_WORDS: a real interjection, not noise.
        labeled = TranscriptionPipeline.assign_speakers(
            [
                seg(
                    0,
                    5,
                    words=words(
                        (0.0, 1.0, "a"),
                        (1.0, 2.0, "b"),
                        (2.0, 3.0, "c"),
                        (3.0, 4.0, "d"),
                        (4.0, 5.0, "e"),
                    ),
                )
            ],
            [
                (0.0, 1.0, "SPEAKER_00"),
                (1.0, 4.0, "SPEAKER_01"),
                (4.0, 5.0, "SPEAKER_00"),
            ],
        )

        assert [w["speaker"] for w in labeled] == [
            "SPEAKER_00",
            "SPEAKER_01",
            "SPEAKER_01",
            "SPEAKER_01",
            "SPEAKER_00",
        ]

    def test_a_flicker_between_two_different_speakers_is_kept(self):
        # Only noise bracketed by the *same* speaker is smoothed away.
        labeled = TranscriptionPipeline.assign_speakers(
            [
                seg(
                    0,
                    3,
                    words=words((0.0, 1.0, "a"), (1.0, 2.0, "b"), (2.0, 3.0, "c")),
                )
            ],
            [
                (0.0, 1.0, "SPEAKER_00"),
                (1.0, 2.0, "SPEAKER_01"),
                (2.0, 3.0, "SPEAKER_02"),
            ],
        )

        assert [w["speaker"] for w in labeled] == [
            "SPEAKER_00",
            "SPEAKER_01",
            "SPEAKER_02",
        ]

    def test_no_words_gives_no_labels(self):
        assert TranscriptionPipeline.assign_speakers([], [(0.0, 1.0, "S")]) == []


# ------------------------------- grouping ---------------------------------- #


def word(start: float, end: float, text: str, speaker: str) -> dict:
    return {"start": start, "end": end, "text": text, "speaker": speaker}


class TestGroupBySpeaker:
    def test_consecutive_words_by_one_speaker_become_one_segment(self):
        grouped = TranscriptionPipeline.group_by_speaker(
            [
                word(0, 1, "one", "SPEAKER_00"),
                word(1, 2, "two", "SPEAKER_00"),
            ]
        )

        assert len(grouped) == 1
        assert grouped[0]["text"] == "one two"
        assert grouped[0]["end"] == 2

    def test_a_speaker_change_starts_a_new_segment(self):
        grouped = TranscriptionPipeline.group_by_speaker(
            [
                word(0, 1, "one", "SPEAKER_00"),
                word(1, 2, "two", "SPEAKER_01"),
            ]
        )

        assert len(grouped) == 2

    def test_empty_input(self):
        assert TranscriptionPipeline.group_by_speaker([]) == []


def spoken(start: float, end: float, speaker: str, text: str, words: int = 1) -> dict:
    return {
        "start": start,
        "end": end,
        "speaker": speaker,
        "text": text,
        "words": [word(start, end, text, speaker) for _ in range(words)],
    }


class TestMergeConsecutive:
    def test_merges_same_speaker_across_a_short_gap(self):
        merged = TranscriptionPipeline.merge_consecutive(
            [spoken(0, 1, "SPEAKER_00", "one"), spoken(1.2, 2, "SPEAKER_00", "two")]
        )

        assert len(merged) == 1
        assert merged[0]["text"] == "one two"
        assert merged[0]["end"] == 2
        assert len(merged[0]["words"]) == 2

    def test_does_not_merge_across_speakers(self):
        merged = TranscriptionPipeline.merge_consecutive(
            [spoken(0, 1, "SPEAKER_00", "one"), spoken(1.1, 2, "SPEAKER_01", "two")]
        )

        assert len(merged) == 2

    def test_does_not_merge_across_a_long_pause(self):
        merged = TranscriptionPipeline.merge_consecutive(
            [spoken(0, 1, "SPEAKER_00", "one"), spoken(5, 6, "SPEAKER_00", "two")]
        )

        assert len(merged) == 2

    def test_stops_merging_past_the_word_ceiling(self):
        merged = TranscriptionPipeline.merge_consecutive(
            [
                spoken(0, 1, "SPEAKER_00", "long", words=50),
                spoken(1.1, 2, "SPEAKER_00", "more"),
            ]
        )

        assert len(merged) == 2

    def test_does_not_mutate_its_input(self):
        first = spoken(0, 1, "SPEAKER_00", "one")
        second = spoken(1.2, 2, "SPEAKER_00", "two")

        TranscriptionPipeline.merge_consecutive([first, second])

        assert first["text"] == "one"
        assert first["end"] == 1
        # The word lists must not be aliased into the merged segment either.
        assert len(first["words"]) == 1

    def test_empty_input(self):
        assert TranscriptionPipeline.merge_consecutive([]) == []


# --------------------------------- result ---------------------------------- #


def test_result_reports_distinct_speakers_sorted():
    from transcriber_pipeline.pipeline import TranscriptionResult

    result = TranscriptionResult(
        segments=[
            {"start": 0, "end": 1, "text": "a", "speaker": "SPEAKER_01"},
            {"start": 1, "end": 2, "text": "b", "speaker": "SPEAKER_00"},
            {"start": 2, "end": 3, "text": "c", "speaker": "SPEAKER_01"},
        ]
    )

    assert result.speakers == ["SPEAKER_00", "SPEAKER_01"]


def test_initial_prompt_combines_punctuation_sample_and_glossary():
    pipeline = TranscriptionPipeline(hf_token="x", glossary="ACME, ProjectX")

    prompt = pipeline._initial_prompt("ru")

    assert "Привет" in prompt
    assert "ACME, ProjectX" in prompt


def test_initial_prompt_is_none_without_language_or_glossary():
    assert TranscriptionPipeline(hf_token="x")._initial_prompt(None) is None


def test_initial_prompt_skips_languages_without_a_sample():
    pipeline = TranscriptionPipeline(hf_token="x", glossary="ACME")

    assert pipeline._initial_prompt("ja") == "ACME"


def test_duration_is_derived_from_the_sample_count():
    from transcriber_pipeline.audio import SAMPLE_RATE, duration_seconds

    assert duration_seconds(np.zeros(SAMPLE_RATE * 3, dtype=np.float32)) == 3.0


# --------------------- pyannote auth-argument selection --------------------- #
#
# 3.x takes `use_auth_token`, 4.x takes `token`. Passing the wrong one is a
# TypeError at container start-up, which is how it was found the first time.


def test_auth_kwarg_uses_the_modern_name_when_offered():
    from transcriber_pipeline.pipeline import auth_kwargs

    def modern(checkpoint, token=None, cache_dir=None):
        pass

    assert auth_kwargs(modern, "hf_x") == {"token": "hf_x"}


def test_auth_kwarg_uses_the_legacy_name_when_that_is_what_exists():
    from transcriber_pipeline.pipeline import auth_kwargs

    def legacy(checkpoint_path, hparams_file=None, use_auth_token=None):
        pass

    assert auth_kwargs(legacy, "hf_x") == {"use_auth_token": "hf_x"}


def test_auth_kwarg_prefers_token_when_a_version_offers_both():
    from transcriber_pipeline.pipeline import auth_kwargs

    def both(checkpoint, token=None, use_auth_token=None):
        pass

    assert auth_kwargs(both, "hf_x") == {"token": "hf_x"}


def test_auth_kwarg_passes_nothing_when_neither_is_declared():
    from transcriber_pipeline.pipeline import auth_kwargs

    def neither(checkpoint, cache_dir=None):
        pass

    # huggingface_hub still picks HF_TOKEN up from the environment.
    assert auth_kwargs(neither, "hf_x") == {}


def test_auth_kwarg_passes_nothing_without_a_token():
    from transcriber_pipeline.pipeline import auth_kwargs

    def modern(checkpoint, token=None):
        pass

    assert auth_kwargs(modern, None) == {}


# ------------------------- checkpoint unpickling ---------------------------- #
#
# torch 2.6 defaults `weights_only` to True, which pyannote 3.x's checkpoints
# fail. torch isn't installed here, so drive the context manager against a stub
# that records what it was handed.


@pytest.fixture
def stub_torch(monkeypatch):
    """Stand in for the `torch` module `trusted_torch_load` imports."""

    import sys
    import types

    calls: list[dict] = []
    module = types.ModuleType("torch")

    def load(path, **kwargs):
        calls.append(kwargs)
        return "checkpoint"

    module.load = load
    module.original_load = load
    monkeypatch.setitem(sys.modules, "torch", module)
    return module, calls


def test_load_defaults_to_the_permissive_unpickler_inside_the_block(stub_torch):
    from transcriber_pipeline.pipeline import trusted_torch_load

    module, calls = stub_torch
    with trusted_torch_load():
        assert module.load("ckpt", map_location="cpu") == "checkpoint"
    assert calls == [{"map_location": "cpu", "weights_only": False}]


def test_load_leaves_an_explicit_weights_only_alone(stub_torch):
    from transcriber_pipeline.pipeline import trusted_torch_load

    module, calls = stub_torch
    with trusted_torch_load():
        module.load("ckpt", weights_only=True)
    assert calls == [{"weights_only": True}]


def test_load_is_restored_when_the_block_ends(stub_torch):
    from transcriber_pipeline.pipeline import trusted_torch_load

    module, calls = stub_torch
    with trusted_torch_load():
        pass
    module.load("ckpt")
    assert module.load is module.original_load
    assert calls == [{}]


def test_load_is_restored_when_the_block_raises(stub_torch):
    from transcriber_pipeline.pipeline import trusted_torch_load

    module, _ = stub_torch
    with pytest.raises(RuntimeError):
        with trusted_torch_load():
            raise RuntimeError("checkpoint is corrupt")
    assert module.load is module.original_load
