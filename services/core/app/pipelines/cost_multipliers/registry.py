"""Handler registry. New multiplier kinds plug in by adding an entry
here — the resolver, the migration tooling and the cost-preview
endpoint then pick them up automatically.
"""

from __future__ import annotations

from .base import CostMultiplierHandler
from .input_field import InputFieldHandler


_HANDLERS: dict[str, CostMultiplierHandler] = {
    InputFieldHandler.type_id: InputFieldHandler(),
}


def get_handler(type_id: str) -> CostMultiplierHandler | None:
    return _HANDLERS.get(type_id)


def registered_types() -> list[str]:
    return list(_HANDLERS.keys())
