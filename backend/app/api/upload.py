"""File upload endpoint: user-supplied geodata becomes a session layer."""
from __future__ import annotations

import geopandas as gpd
from fastapi import APIRouter, File, HTTPException, UploadFile

from ..workspace import store

router = APIRouter()


@router.post("/sessions/{session_id}/upload")
async def upload(session_id: str, file: UploadFile = File(...)):
    try:
        session = store.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    dest = session.dir / "uploads"
    dest.mkdir(exist_ok=True)
    path = dest / file.filename
    path.write_bytes(await file.read())

    try:
        gdf = gpd.read_file(path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read geodata: {exc}")

    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)
    layer = session.add_layer(gdf.to_crs(epsg=4326), file.filename, source="upload")

    # Let the agent know (in its history) that a layer was added out-of-band.
    session.history.append({
        "role": "user",
        "content": f"[system] The user uploaded file '{file.filename}', loaded as "
        f"layer '{layer.id}' ({layer.geometry_type()}, {len(gdf)} features).",
    })
    return {"layer": layer.to_descriptor()}
