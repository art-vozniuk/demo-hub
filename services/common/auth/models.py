from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    id: str
    email: Optional[str] = None
    metadata: Optional[dict] = None
