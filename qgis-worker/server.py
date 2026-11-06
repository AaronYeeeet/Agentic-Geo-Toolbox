"""MCP server with PyQGIS.

QGIS is loaded once at startup and stays in memory.
Tools run one after another on the main thread, because PyQGIS is not thread-safe.
"""

import sys

from qgis.core import Qgis, QgsApplication

# Start QGIS without a GUI
QgsApplication.setPrefixPath("/usr", True)
qgs = QgsApplication([], False)
qgs.initQgis()

# Load Processing: QGIS, GDAL and GRASS algorithms
sys.path.append("/usr/share/qgis/python/plugins")
import processing  # noqa: E402
from processing.core.Processing import Processing  # noqa: E402

Processing.initialize()

from qgis.analysis import QgsNativeAlgorithms  # noqa: E402

if not QgsApplication.processingRegistry().providerById("native"):
    QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())

from catalog import build_catalog  # noqa: E402

# Read once at startup; the algorithms don't change while the worker runs
CATALOG = build_catalog()
CATALOG_BY_ID = {alg["id"]: alg for alg in CATALOG}

from mcp.server.fastmcp import FastMCP  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

mcp = FastMCP("geo-tools", host="0.0.0.0", port=8100)


@mcp.tool()
def qgis_version() -> str:
    """Return the running QGIS version."""
    return Qgis.version()


@mcp.tool()
def run_algorithm(algorithm_id: str, parameters: dict) -> dict:
    """Run a QGIS Processing algorithm, e.g. native:buffer.

    Write outputs to a file path under /data, e.g. "OUTPUT": "/data/result.gpkg".
    """
    result = processing.run(algorithm_id, parameters)
    return {key: str(value) for key, value in result.items()}


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    count = len(QgsApplication.processingRegistry().algorithms())
    return JSONResponse({"qgis": Qgis.version(), "algorithms": count, "catalog": len(CATALOG)})


@mcp.custom_route("/catalog", methods=["GET"])
async def catalog(request: Request) -> JSONResponse:
    """For debugging: /catalog, /catalog?provider=native, /catalog?id=native:buffer"""
    alg_id = request.query_params.get("id")
    if alg_id:
        if alg_id not in CATALOG_BY_ID:
            return JSONResponse({"error": f"unknown algorithm: {alg_id}"}, status_code=404)
        return JSONResponse(CATALOG_BY_ID[alg_id])
    provider = request.query_params.get("provider")
    algorithms = [a for a in CATALOG if not provider or a["provider"] == provider]
    return JSONResponse({"count": len(algorithms), "algorithms": algorithms})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
