"""Raised when seat credentials cannot be loaded or used. Its message never holds a secret value."""
from __future__ import annotations


class CredentialsError(RuntimeError):
    """Doppler could not be read, a required key is missing or malformed, or the login was refused."""
