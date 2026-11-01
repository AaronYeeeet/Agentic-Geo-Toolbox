from pathlib import Path

import os

from dotenv import dotenv_values
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

# Keys that came from .env (not from the shell), so a later reload may update them.
_from_env_file: set[str] = set()


def load_env_keys() -> None:
    """Export every .env entry to os.environ, so LiteLLM finds whatever provider
    key is set there (GEMINI_API_KEY, OPENROUTER_API_KEY, ...).

    Called again before listing models and before each chat, so a key added to
    .env works without a restart (`uvicorn --reload` only watches .py files).
    Empty values are skipped: `KEY=` would otherwise count as "key present".
    Variables set in the shell win over .env.
    """
    values = dotenv_values(ENV_FILE)
    for key, value in values.items():
        if value and (key not in os.environ or key in _from_env_file):
            os.environ[key] = value
            _from_env_file.add(key)
    for key in [k for k in _from_env_file if not values.get(k)]:  # emptied or removed
        os.environ.pop(key, None)
        _from_env_file.discard(key)


load_env_keys()


class Settings(BaseSettings):
    """Central configuration, loaded from environment / .env file."""

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    llm_model: str = "anthropic/claude-opus-5-5"
    anthropic_api_key: str = ""
    llm_api_base: str = ""
    agent_max_steps: int = 12
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Root folder for per-session workspaces (uploads, generated layers, traces).
    workspace_root: Path = Path(__file__).resolve().parent.parent / "workspace"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
settings.workspace_root.mkdir(parents=True, exist_ok=True)
