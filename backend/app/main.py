"""API backend. The agent will live here."""

import os

import httpx
import psycopg
from fastapi import FastAPI
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

DATABASE_URL = os.environ["DATABASE_URL"]
MCP_URL = os.environ.get("MCP_URL", "http://qgis:8100/mcp")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://litellm:4000")
LLM_MODEL = os.environ.get("LLM_MODEL", "default")
LITELLM_MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "")

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
        async with (
            streamablehttp_client(MCP_URL) as (read, write, _),
            ClientSession(read, write) as session,
        ):
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


async def check_llm() -> dict:
    """Only checks that the proxy is up. Does not call a model, so it costs nothing."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{LLM_BASE_URL}/health/liveliness")
            r.raise_for_status()
        return {"ok": True, "proxy": LLM_BASE_URL, "model": LLM_MODEL}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/health")
async def health() -> dict:
    return {
        "backend": {"ok": True},
        "database": await check_database(),
        "qgis": await check_qgis(),
        "llm": await check_llm(),
    }


@app.get("/api/llm-ping")
async def llm_ping() -> dict:
    """Sends one short prompt through the proxy to check that a model really answers."""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{LLM_BASE_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {LITELLM_MASTER_KEY}"},
                json={
                    "model": LLM_MODEL,
                    "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
                    # Reasoning models think first; too low a limit gives reply=None.
                    "max_tokens": 300,
                },
            )
            r.raise_for_status()
            data = r.json()
        return {
            "ok": True,
            "reply": data["choices"][0]["message"]["content"],
            "model": data.get("model"),
        }
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"{e.response.status_code}: {e.response.text[:300]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
