"""A task a seat holds, as claim_next returns it."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class ClaimedTask:
    task_id: UUID
    lease_version: int
    lease_until: datetime
    title: str
    done_when: str
    risk_tier: str
    roles_needed: tuple[str, ...]
    roadmap_ref: str | None
    body: Mapping[str, Any]
