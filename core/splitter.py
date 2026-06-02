# 中文文本切分 + 标题增强模块
import re
from typing import List, Optional, Any
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pathlib import Path
from configs import CHUNK_SIZE, CHUNK_OVERLAP, ZH_TITLE_ENHANCE

# ---- 切分器底层工具 ----
def _split_text_with_regex_from_end(text: str, separator: str, keep_separator: bool) -> List[str]:
    if separator:
        if keep_separator:
            _splits = re.split(f"({separator})", text)
            splits = ["".join(i) for i in zip(_splits[0::2], _splits[1::2])]
            if len(_splits) % 2 == 1:
                splits += _splits[-1:]
        else:
            splits = re.split(separator, text)
    else:
        splits = list(text)
    return [s for s in splits if s != ""]

# ---- 中文递归切分器 ----
class ChineseRecursiveTextSplitter(RecursiveCharacterTextSplitter):
    def __init__(self, separators=None, keep_separator=True, is_separator_regex=True, **kwargs):
        super().__init__(keep_separator=keep_separator, **kwargs)
        self._separators = separators or [
            r"\n\n", r"\n", r"。|！|？", r"\.\s|\!\s|\?\s", r"；|;\s", r"，|,\s"
        ]
        self._is_separator_regex = is_separator_regex

    def _split_text(self, text: str, separators: List[str]) -> List[str]:
        final_chunks = []
        separator = separators[-1]
        new_separators = []
        for i, _s in enumerate(separators):
            _separator = _s if self._is_separator_regex else re.escape(_s)
            if _s == "":
                separator = _s
                break
            if re.search(_separator, text):
                separator = _s
                new_separators = separators[i + 1:]
                break
        _separator = separator if self._is_separator_regex else re.escape(separator)
        splits = _split_text_with_regex_from_end(text, _separator, self._keep_separator)
        _good_splits = []
        _separator = "" if self._keep_separator else separator
        for s in splits:
            if self._length_function(s) < self._chunk_size:
                _good_splits.append(s)
            else:
                if _good_splits:
                    merged_text = self._merge_splits(_good_splits, _separator)
                    final_chunks.extend(merged_text)
                    _good_splits = []
                if not new_separators:
                    final_chunks.append(s)
                else:
                    other_info = self._split_text(s, new_separators)
                    final_chunks.extend(other_info)
        if _good_splits:
            merged_text = self._merge_splits(_good_splits, _separator)
            final_chunks.extend(merged_text)
        return [re.sub(r"\n{2,}", "\n", chunk.strip()) for chunk in final_chunks if chunk.strip()!=""]

# ---- 标题增强 ----
def under_non_alpha_ratio(text: str, threshold: float = 0.5) -> bool:
    if len(text) == 0:
        return False
    alpha_count = len([char for char in text if char.strip() and char.isalpha()])
    total_count = len([char for char in text if char.strip()])
    try:
        return (alpha_count / total_count) < threshold
    except:
        return False

def is_possible_title(text: str, title_max_word_length: int = 20, non_alpha_threshold: float = 0.5) -> bool:
    if len(text) == 0:
        return False
    if re.search(r"[^\w\s]\Z", text):
        return False
    if len(text) > title_max_word_length:
        return False
    if under_non_alpha_ratio(text, threshold=non_alpha_threshold):
        return False
    if text.endswith((",", ".", "\uff0c", "\u3002")):
        return False
    if text.isnumeric():
        return False
    text_5 = text[:5] if len(text) >= 5 else text
    if not any(c.isnumeric() for c in text_5):
        return False
    return True

def zh_title_enhance(docs: List[Document]) -> List[Document]:
    title = None
    if len(docs) > 0:
        for doc in docs:
            if is_possible_title(doc.page_content):
                doc.metadata["category"] = "cn_Title"
                title = doc.page_content
            elif title:
                doc.page_content = f"下文与({title})有关。{doc.page_content}"
        return docs
    else:
        print("文档为空")
        return docs

# ---- 统一入口 ----
def load_and_split_documents(folder: str) -> List[Document]:
    """从文件夹加载所有 .md/.txt，切分并可选标题增强，返回 Document 列表"""
    text_splitter = ChineseRecursiveTextSplitter(
        keep_separator=True, is_separator_regex=True,
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP,
    )
    all_chunks = []
    for file_path in Path(folder).iterdir():
        if file_path.is_file() and file_path.suffix in {".txt", ".md"}:
            content = file_path.read_text(encoding="utf-8-sig")
            doc = Document(page_content=content, metadata={"source": file_path.name})
            chunks = text_splitter.split_documents([doc])
            if ZH_TITLE_ENHANCE:
                chunks = zh_title_enhance(chunks)
            for i, chunk in enumerate(chunks):
                chunk.metadata["chunk"] = i
                chunk.metadata["source"] = file_path.name
            all_chunks.extend(chunks)
            print(f"  [LOAD] {file_path.name} ({len(content)} 字) → 切成 {len(chunks)} 块")
    return all_chunks
