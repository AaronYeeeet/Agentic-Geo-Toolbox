from fastapi import APIRouter

from app import __version__
from app.config import get_settings

router = APIRouter()


@router.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent_mode": get_settings().agent_mode, "version": __version__}
