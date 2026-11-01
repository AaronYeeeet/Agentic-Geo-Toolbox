from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agent import llm, tools  # noqa: F401  (importing tools registers them)
from .agent.registry import all_tools
from .api import chat, upload
from .config import settings

app = FastAPI(title="Agentic Geo Toolbox API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api")
app.include_router(upload.router, prefix="/api")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "model": settings.llm_model,
        "llm_configured": llm.is_configured(),
        "llm_missing_keys": llm.missing_keys(),
        "tools": sorted(all_tools().keys()),
    }
