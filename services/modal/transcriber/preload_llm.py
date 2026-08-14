#!/usr/bin/env python3
"""Add the optional transcript-cleanup LLM to the transcriber-models volume.

Separate from preload.py because it is by far the biggest download
(~15GB for Qwen2.5-7B in bf16, quantised to 4-bit NF4 at load) and the
feature is off by default. Until this has run, a request with
`llm_cleanup: true` fails fast with a pointer back here rather than
pulling 15GB inside a request that would then blow the pipeline deadline.

Runs on a Modal CPU container. Idempotent.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from common.cli import preload  # noqa: E402


if __name__ == "__main__":
    preload("transcriber/app.py", function="preload_llm_weights")
