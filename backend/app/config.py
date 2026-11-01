from pathlib import Path

import os

from dotenv import dotenv_values
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

# Export every .env entry to os.environ, so LiteLLM finds whatever provider key
# is set there (GEMINI_API_KEY, GROQ_API_KEY, ANTHROPIC_API_KEY, ...). Empty
# values are skipped: `KEY=` would otherwise count as "key present".
for _key, _value in dotenv_values(ENV_FILE).items():
    if _value and _key not in os.environ:
        os.environ[_key] = _value


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
