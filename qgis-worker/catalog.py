"""Catalog of all QGIS Processing algorithms in a simple, JSON-friendly form.

Built once at startup from the processing registry, so it always matches the installed QGIS.
Later used by search_tools / describe_tool (ticket W2).
"""

import re

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsProcessingAlgorithm,
    QgsProcessingParameterDefinition,
)

# QGIS parameter types -> simpler names for the model. Unknown types keep their QGIS name.
SIMPLE_TYPES = {
    "source": "vector_layer",
    "vector": "vector_layer",
    "raster": "raster_layer",
    "mesh": "mesh_layer",
    "layer": "layer",
    "multilayer": "layer_list",
    "number": "number",
    "distance": "distance",
    "area": "area",
    "duration": "duration",
    "scale": "scale",
    "range": "range",
    "enum": "enum",
    "field": "field",
    "band": "raster_band",
    "boolean": "boolean",
    "string": "text",
    "expression": "expression",
    "crs": "crs",
    "extent": "extent",
    "point": "point",
    "geometry": "geometry",
    "file": "file",
    "color": "color",
}

TAG = re.compile(r"<[^>]+>")


def _text(value: str) -> str:
    """Help texts may contain HTML; keep only plain text."""
    return TAG.sub("", value or "").strip()


def _json_value(value):
    """Default values can be QGIS objects; make them JSON-safe."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return str(value)


def _parameter(param: QgsProcessingParameterDefinition) -> dict:
    flags = param.flags()
    qgis_type = param.type()
    entry = {
        "name": param.name(),
        "description": param.description(),
        "type": "output" if param.isDestination() else SIMPLE_TYPES.get(qgis_type, qgis_type),
        "qgis_type": qgis_type,
        "required": not (flags & Qgis.ProcessingParameterFlag.Optional),
        "advanced": bool(flags & Qgis.ProcessingParameterFlag.Advanced),
    }
    default = _json_value(param.defaultValue())
    if default is not None:
        entry["default"] = default
    if param.help():
        entry["help"] = _text(param.help())

    # Extra details the model needs to fill the parameter correctly
    if qgis_type == "enum":
        entry["options"] = param.options()
        entry["multiple"] = param.allowMultiple()
        # QGIS stores the default as an index; show the option text instead
        if isinstance(default, int) and 0 <= default < len(entry["options"]):
            entry["default"] = entry["options"][default]
    elif qgis_type in ("number", "distance"):
        if param.minimum() > -1e300:
            entry["minimum"] = param.minimum()
        if param.maximum() < 1e300:
            entry["maximum"] = param.maximum()
        if qgis_type == "distance":
            # Distances are in the units of this layer's CRS (degrees for EPSG:4326)
            entry["unit_from"] = param.parentParameterName()
    elif qgis_type == "field":
        entry["layer_from"] = param.parentLayerParameterName()
        entry["multiple"] = param.allowMultiple()
    elif qgis_type == "band":
        entry["layer_from"] = param.parentLayerParameterName()
    return entry


def _algorithm(alg: QgsProcessingAlgorithm) -> dict:
    description = _text(alg.shortHelpString()) or _text(alg.shortDescription())
    return {
        "id": alg.id(),
        "name": alg.displayName(),
        "provider": alg.provider().id(),
        "group": alg.group(),
        "tags": alg.tags(),
        "description": description,
        "parameters": [_parameter(p) for p in alg.parameterDefinitions()],
    }


def build_catalog() -> list[dict]:
    """All usable algorithms, sorted by id. Deprecated and hidden ones are left out."""
    skip = Qgis.ProcessingAlgorithmFlag.Deprecated | Qgis.ProcessingAlgorithmFlag.HideFromToolbox
    algorithms = [
        _algorithm(alg)
        for alg in QgsApplication.processingRegistry().algorithms()
        if not (alg.flags() & skip)
    ]
    return sorted(algorithms, key=lambda a: a["id"])
