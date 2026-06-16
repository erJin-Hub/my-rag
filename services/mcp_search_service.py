import json
import re
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from configs import MCP_SEARCH_COMMAND, MCP_SEARCH_SCRIPT, MCP_SEARCH_TOOL

ROOT_DIR = Path(__file__).resolve().parents[1]


def compact_text(text: str, max_chars: int = 260) -> str:
    cleaned = re.sub(r"!\[[^\]]*]\([^)]+\)", "", str(text or ""))
    cleaned = re.sub(r"\[[^\]]+]\([^)]+\)", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if len(cleaned) <= max_chars else f"{cleaned[:max_chars].rstrip()}..."


def normalize_search_result(item: dict) -> dict:
    return {
        "title": compact_text(item.get("title", ""), 80),
        "url": str(item.get("url", "")).strip(),
        "snippet": compact_text(item.get("snippet", ""), 260),
    }


def parse_tool_payload(result) -> dict:
    structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if structured:
        return dict(structured)

    for content in result.content:
        if isinstance(content, TextContent):
            try:
                return json.loads(content.text)
            except json.JSONDecodeError:
                continue
    return {"results": [], "error": "MCP tool returned no JSON payload"}


async def search_web_with_mcp(query: str, limit: int = 3) -> tuple[str, list[dict]]:
    script_path = Path(MCP_SEARCH_SCRIPT)
    if not script_path.is_absolute():
        script_path = ROOT_DIR / script_path

    command = MCP_SEARCH_COMMAND
    # 系统可能会找到全局 Python，不一定是当前项目虚拟环境里的 Python。
    if command.lower() in {"python", "python.exe"}:
        # sys.executable 表示“当前运行这个 FastAPI 项目的 Python 解释器”
        command = sys.executable

    server = StdioServerParameters(
        command=command,
        args=[str(script_path)],
        cwd=str(ROOT_DIR),
    )

    try:
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    MCP_SEARCH_TOOL,
                    {"query": query, "limit": limit},
                )
    except Exception as exc:
        print(f"[MCP Search] 调用 web_search 失败: {exc}")
        return "", []

    payload = parse_tool_payload(result)
    error = str(payload.get("error") or "").strip()
    if error:
        print(f"[MCP Search] web_search 返回错误: {error}")

    results = [
        normalize_search_result(item)
        for item in payload.get("results", [])
        if isinstance(item, dict)
    ]
    results = [item for item in results if item["title"] or item["snippet"] or item["url"]]
    return format_search_context(results), results


def format_search_context(results: list[dict]) -> str:
    lines = []
    for index, item in enumerate(results, start=1):
        lines.append(
            f"{index}. {item['title']}\n"
            f"URL: {item['url']}\n"
            f"摘要: {item['snippet']}"
        )
    return "\n\n".join(lines)
