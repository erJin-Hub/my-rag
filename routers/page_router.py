import os

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

from configs.app_paths import WEB_DIR

router = APIRouter()


@router.get("/")
async def root():
    return RedirectResponse(url="/static/index.html")


@router.get("/documents")
async def documents_page():
    return FileResponse(os.path.join(WEB_DIR, "documents.html"))


@router.get("/memories")
async def memories_page():
    return FileResponse(os.path.join(WEB_DIR, "memories.html"))
