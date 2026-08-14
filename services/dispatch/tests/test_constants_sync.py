"""Guards the mirror between services/common/constants.py and
services/modal/common/constants.py — if it fails, update the other copy."""

import importlib.util
from pathlib import Path

from services.common import constants as canonical

_MODAL_CONSTANTS = (
    Path(__file__).resolve().parents[2] / "modal" / "common" / "constants.py"
)


def _load_modal_constants():
    spec = importlib.util.spec_from_file_location("modal_constants", _MODAL_CONSTANTS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_modal_function_timeout_matches_pipeline_deadline():
    modal_constants = _load_modal_constants()
    assert (
        modal_constants.MODAL_FUNCTION_TIMEOUT_SECONDS
        == canonical.MODAL_PIPELINE_DEADLINE_SECONDS
    )


def test_modal_long_function_timeout_matches_long_pipeline_deadline():
    modal_constants = _load_modal_constants()
    assert (
        modal_constants.MODAL_LONG_FUNCTION_TIMEOUT_SECONDS
        == canonical.MODAL_LONG_PIPELINE_DEADLINE_SECONDS
    )


def test_long_deadline_is_longer_than_the_default():
    assert (
        canonical.MODAL_LONG_PIPELINE_DEADLINE_SECONDS
        > canonical.MODAL_PIPELINE_DEADLINE_SECONDS
    )


def test_top_buckets_equal_deadlines():
    # Duration buckets top out at the *longest* deadline any pipeline can run
    # to, so a long transcription lands on the chart instead of in +Inf.
    assert (
        canonical.INFERENCE_BUCKETS[-1]
        == canonical.MODAL_LONG_PIPELINE_DEADLINE_SECONDS
    )
    assert canonical.QUEUE_WAIT_BUCKETS[-1] == canonical.MODAL_PIPELINE_DEADLINE_SECONDS
    assert (
        canonical.E2E_BUCKETS[-1] == 2 * canonical.MODAL_LONG_PIPELINE_DEADLINE_SECONDS
    )
    for buckets in (
        canonical.INFERENCE_BUCKETS,
        canonical.QUEUE_WAIT_BUCKETS,
        canonical.E2E_BUCKETS,
        canonical.COLD_START_BUCKETS,
        canonical.HTTP_BUCKETS,
        canonical.DB_BUCKETS,
    ):
        assert list(buckets) == sorted(set(buckets))
