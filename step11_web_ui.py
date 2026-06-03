"""
第11步：原生 HTML + JavaScript 前端页面

复用 step10_memory.py 里的 FastAPI app 和记忆接口，增加浏览器聊天页面：
  - GET /                  打开 web/index.html
  - /static/*              前端 JS/CSS 静态文件
  - 继续使用 step10 的 API 作为后端
"""
import asyncio
import os

import uvicorn
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from step10_memory import app


BASE_DIR = os.path.dirname(__file__)
WEB_DIR = os.path.join(BASE_DIR, "web")

app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/")
def web_index():
    return FileResponse(
        os.path.join(WEB_DIR, "index.html"),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


if __name__ == "__main__":
    config = uvicorn.Config(app, host="127.0.0.1", port=8000)
    server = uvicorn.Server(config)
    asyncio.run(server.serve())
