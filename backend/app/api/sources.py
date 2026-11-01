from fastapi import APIRouter

from app.sources.registry import Source, SourceStatus, load_registry

router = APIRouter()


@router.get("/api/sources")
def list_sources(status: SourceStatus | None = None) -> dict[str, list[Source]]:
    sources = load_registry()
    if status is not None:
        sources = [source for source in sources if source.status == status]
    return {"sources": sources}
