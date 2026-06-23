import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
TAVILY_SEARCH_URL = os.getenv("TAVILY_SEARCH_URL", "https://api.tavily.com/search")

mcp = FastMCP("my-rag-web-search")


@mcp.tool()
async def web_search(query: str, limit: int = 3) -> dict:
    """Search the web and return title/url/snippet results."""
    query = (query or "").strip()
    limit = max(1, min(int(limit or 3), 5))
    if not query:
        return {"results": [], "error": "query is empty"}
    if not TAVILY_API_KEY:
        return {"results": [], "error": "TAVILY_API_KEY is not configured"}

    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "max_results": limit,
        "search_depth": "basic",
        "include_answer": False,
        "include_raw_content": False,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(TAVILY_SEARCH_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"results": [], "error": str(exc)}

    results = []
    for item in data.get("results", [])[:limit]:
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", ""),
        })
    return {"results": results, "error": ""}


if __name__ == "__main__":
    mcp.run()
