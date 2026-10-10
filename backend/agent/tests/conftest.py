"""Settings every test runs under."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_resumed_processing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A test that starts the API's lifespan must never resume processing the
    real flights of the laptop it runs on (api/rest.py, lifespan)."""
    monkeypatch.setenv("CROPWATCHER_RESUME", "0")
