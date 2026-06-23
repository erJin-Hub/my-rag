import json
import os
from collections import Counter
from pathlib import Path

import faiss
import numpy as np
from fastapi import HTTPException
from langchain_core.documents import Document

import configs
from core.document_loader import SUPPORTED_SUFFIXES, extract_text_from_bytes
from core.embedding import embed_texts
from core.splitter import ChineseRecursiveTextSplitter, zh_title_enhance

ALLOWED_SUFFIXES = SUPPORTED_SUFFIXES


async def upload_document_to_knowledge_base(app, file, docs_dir: str, index_path: str, docs_path: str) -> dict:
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"不支持的文件类型: {suffix}，只支持 {sorted(ALLOWED_SUFFIXES)}")

    file_bytes = await file.read()
    try:
        content = extract_text_from_bytes(file_bytes, file.filename)
    except Exception as exc:
        raise HTTPException(400, f"文件解析失败：{exc}") from exc

    file_path = os.path.join(docs_dir, file.filename)
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    new_chunks = split_uploaded_content(content, file.filename)
    if not new_chunks:
        os.remove(file_path)
        raise HTTPException(400, "文件内容为空或无法切分")

    embeddings = embed_texts([chunk.page_content for chunk in new_chunks])
    app.state.index.add(np.array(embeddings, dtype=np.float32))
    app.state.documents.extend(new_chunks)
    persist_knowledge_base(app, index_path, docs_path)

    print(f"[Upload] {file.filename} -> {len(new_chunks)} 块，总计 {app.state.index.ntotal} 块")
    return {"filename": file.filename, "chunks": len(new_chunks), "total_chunks": app.state.index.ntotal}


def split_uploaded_content(content: str, filename: str) -> list[Document]:
    splitter = ChineseRecursiveTextSplitter(
        keep_separator=True,
        is_separator_regex=True,
        chunk_size=configs.CHUNK_SIZE,
        chunk_overlap=configs.CHUNK_OVERLAP,
    )
    doc = Document(page_content=content, metadata={"source": filename})
    chunks = splitter.split_documents([doc])
    if configs.ZH_TITLE_ENHANCE:
        chunks = zh_title_enhance(chunks)
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk"] = i
        chunk.metadata["source"] = filename
    return chunks


def persist_knowledge_base(app, index_path: str, docs_path: str) -> None:
    faiss.write_index(app.state.index, index_path)
    doc_dicts = [{"content": d.page_content, "metadata": d.metadata} for d in app.state.documents]
    with open(docs_path, "w", encoding="utf-8") as f:
        json.dump(doc_dicts, f, ensure_ascii=False, indent=2)


def list_knowledge_documents(app) -> dict:
    counter = Counter(d.metadata.get("source", "?") for d in app.state.documents)
    return {
        "total_chunks": app.state.index.ntotal,
        "files": [{"filename": filename, "chunks": chunks} for filename, chunks in counter.items()],
    }
