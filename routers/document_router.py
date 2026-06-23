from fastapi import APIRouter, File, Request, UploadFile

from configs.app_paths import DOCS_DIR, DOCS_PATH, INDEX_PATH
from schemas.chat import UploadResponse
from services.document_service import list_knowledge_documents, upload_document_to_knowledge_base

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("/upload", response_model=UploadResponse)
async def upload_document(request: Request, file: UploadFile = File(...)):
    result = await upload_document_to_knowledge_base(
        request.app,
        file,
        DOCS_DIR,
        INDEX_PATH,
        DOCS_PATH,
    )
    return UploadResponse(**result)


@router.get("/list")
def list_documents(request: Request):
    return list_knowledge_documents(request.app)
