"""API backend. The agent will live here."""

import os

import psycopg
from fastapi import FastAPI
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

DATABASE_URL = os.environ["DATABASE_URL"]
MCP_URL = os.environ.get("MCP_URL", "http://qgis:8100/mcp")

app = FastAPI(title="Geo-Agent")


async def check_database() -> dict:
    try:
        async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
            cur = await conn.execute("SELECT postgis_lib_version()")
            (version,) = await cur.fetchone()
        return {"ok": True, "postgis": version}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def check_qgis() -> dict:
    try:
        async with streamablehttp_client(MCP_URL) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                reply = await session.call_tool("qgis_version", {})
        return {
            "ok": True,
            "qgis": reply.content[0].text,
            "tools": [tool.name for tool in tools.tools],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/health")
async def health() -> dict:
    return {
        "backend": {"ok": True},
        "database": await check_database(),
        "qgis": await check_qgis(),
    }
