"""Mirror of Modal-relevant values from services/common/constants.py (out of
import reach for Modal images); kept in sync by test_constants_sync.py."""

# == services.common.constants.MODAL_PIPELINE_DEADLINE_SECONDS
MODAL_FUNCTION_TIMEOUT_SECONDS = 600

# == services.common.constants.MODAL_LONG_PIPELINE_DEADLINE_SECONDS
# For functions whose work scales with input size (transcription) rather than
# being a fixed forward pass. Must equal the dispatch-side deadline those
# pipelines poll to, so the container and the poller give up together.
MODAL_LONG_FUNCTION_TIMEOUT_SECONDS = 1800
