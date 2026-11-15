from __future__ import annotations


class ApplicationError(ValueError):
    """A public input or permission failure shared by local adapters."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
