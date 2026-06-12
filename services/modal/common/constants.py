"""Mirror of the Modal-relevant values from services/common/constants.py.

Modal app entrypoints can only import the `common` package that ships
into their images (services/modal/common), so the canonical module is
out of reach. Keep this file tiny and let
services/common/tests/test_constants_sync.py fail CI the moment the two
copies disagree.
"""

# == services.common.constants.MODAL_PIPELINE_DEADLINE_SECONDS — the Modal
# function timeout and the dispatch poll deadline must give up together.
MODAL_FUNCTION_TIMEOUT_SECONDS = 600
