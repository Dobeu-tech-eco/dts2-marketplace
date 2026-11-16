"""Raised when a seat no longer holds the task at the lease version it passed."""
from __future__ import annotations

LEASE_LOST_SQLSTATE: str = "55000"


class LeaseLostError(RuntimeError):
    """The lease lapsed, was released, or another seat now holds the task. Stop work on it."""
