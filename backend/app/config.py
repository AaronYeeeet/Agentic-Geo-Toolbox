"""Runtime settings read from the environment (see .env.example)."""

import os
from dataclasses import dataclass, field


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    agent_mode: str = field(default_factory=lambda: os.environ.get("AGENT_MODE", "mock"))
    cors_origins: list[str] = field(
        default_factory=lambda: _split(os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"))
    )
    # MOCK_FAST=1 removes the artificial delays of the mock agent (tests, screenshots).
    mock_fast: bool = field(default_factory=lambda: os.environ.get("MOCK_FAST", "0") == "1")


def get_settings() -> Settings:
    return Settings()
