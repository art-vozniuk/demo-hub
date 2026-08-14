#!/usr/bin/env python3
"""Populate the transcriber-models volume with the Whisper sizes the UI
offers plus the pyannote diarization pipeline.

Runs on a Modal CPU container (no local GPU needed). Idempotent.
The cleanup LLM is a separate, much larger download — see preload_llm.py.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from common.cli import preload  # noqa: E402


if __name__ == "__main__":
    preload("transcriber/app.py")
