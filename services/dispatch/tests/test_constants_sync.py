"""Guards the mirror between services/common/constants.py (canonical)
and services/modal/common/constants.py (shipped into Modal images,
which cannot import services.common). If this fails, someone changed
one copy — update the other."""

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


def test_top_buckets_equal_deadlines():
    assert canonical.INFERENCE_BUCKETS[-1] == canonical.MODAL_PIPELINE_DEADLINE_SECONDS
    assert canonical.QUEUE_WAIT_BUCKETS[-1] == canonical.MODAL_PIPELINE_DEADLINE_SECONDS
    assert canonical.E2E_BUCKETS[-1] == 2 * canonical.MODAL_PIPELINE_DEADLINE_SECONDS
    for buckets in (
        canonical.INFERENCE_BUCKETS,
        canonical.QUEUE_WAIT_BUCKETS,
        canonical.E2E_BUCKETS,
        canonical.COLD_START_BUCKETS,
        canonical.HTTP_BUCKETS,
        canonical.DB_BUCKETS,
    ):
        assert list(buckets) == sorted(set(buckets))
