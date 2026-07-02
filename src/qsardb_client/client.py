"""Minimal QsarDB client entry point."""

from __future__ import annotations

import httpx


class QsarDBClient:
    """Lightweight client shell for future QsarDB integration work.

    Network-backed catalogue fetching, prediction, archive downloading, and
    QDB archive parsing are intentionally outside the M0/M1 scope.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float | httpx.Timeout = 30.0,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
