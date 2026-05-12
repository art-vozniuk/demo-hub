"""Shared base for compute pipelines.

Concrete pipelines live in sibling modules (`face_recognition.py`,
`face_swap.py`). Each one runs inside `_inference_lock` in service.py
so the single GPU isn't oversubscribed.
"""

from __future__ import annotations


class Pipeline:
    def __init__(self) -> None:
        pass

    def run(self) -> dict:
        raise NotImplementedError
