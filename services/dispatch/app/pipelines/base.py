"""Shared base for async dispatch pipelines. Concrete classes live in
sibling modules (generative_editing.py, sharp.py). """

from __future__ import annotations

from typing import Any


class AsyncPipeline:
    async def run(self) -> dict[str, Any]:
        raise NotImplementedError
