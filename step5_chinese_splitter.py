"""
第5步：中文优化切分 + 标题增强
基于 step4，引入 hw-chat 的两大中文优化：
  - 中文分号/逗点优先的正则切分
  - 标题识别与增强（父标题->子块添加关联）
"""
import httpx, jwt, time, json, os, re, sys
import numpy as np
import faiss
from typing import List, Optional, Any
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pathlib import Path

# 统一输出编码为 UTF-8
sys.stdout.reconfigure(encoding="utf-8")

# ==================== 0. API 配置 ====================
API_KEY = "f319167f721645fe91aa4918d321b521.bPLyCmwCzSOr1Ttb"
EMBED_URL = "https://open.bigmodel.cn/api/paas/v4/embeddings"
CHAT_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

def generate_token(apikey, exp_seconds=60):
    api_id, secret = apikey.split(".")
    payload = {"api_key": api_id, "exp": int(round(time.time()*1000)) + exp_seconds*1000,
               "timestamp": int(round(time.time()*1000))}
    return jwt.encode(payload, secret, algorithm="HS256",
                      headers={"alg": "HS256", "sign_type": "SIGN"})

def embed_texts(texts: List[str]) -> List[List[float]]:
    token = generate_token(API_KEY)
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    embeddings = []
    with httpx.Client(timeout=30) as client:
        for text in texts:
            resp = client.post(EMBED_URL, headers=headers,
                               json={"model": "embedding-2", "input": text})
            embeddings.append(resp.json()["data"][0]["embedding"])
    return embeddings

# ==================== 1. 路径 ====================
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")
INDEX_PATH = os.path.join(DATA_DIR, "faiss.index")
DOCS_PATH = os.path.join(DATA_DIR, "documents.json")
os.makedirs(DATA_DIR, exist_ok=True)

# ==================== 2.1 辅助：正则切分（保留分隔符） ====================
def _split_text_with_regex_from_end(
        text: str, separator: str, keep_separator: bool
) -> List[str]:
    """正则切分，可选择保留分隔符"""
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

# ==================== 2.2 ChineseRecursiveTextSplitter ====================
class ChineseRecursiveTextSplitter(RecursiveCharacterTextSplitter):
    """
    中文文本切分器，新增能力：
    - 分隔符使用中文标点正则（句号、感叹、问号、分号、逗号）
    - 优先按句子切分，再按段落、逐字符退化
    - 合并后清理多余空行
    """
    def __init__(
            self,
            separators: Optional[List[str]] = None,
            keep_separator: bool = True,
            is_separator_regex: bool = True,
            **kwargs: Any,
    ) -> None:
        super().__init__(keep_separator=keep_separator, **kwargs)
        # 默认中文正则分隔符（优先级从高到低）
        self._separators = separators or [
            r"\n\n",
            r"\n",
            r"。|！|？",
            r"\.\s|\!\s|\?\s",
            r"；|;\s",
            r"，|,\s"
        ]
        self._is_separator_regex = is_separator_regex

    def _split_text(self, text: str, separators: List[str]) -> List[str]:
        """递归切分"""
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

# ==================== 2.3 标题增强 ====================
def under_non_alpha_ratio(text: str, threshold: float = 0.5) -> bool:
    """非字母占比过高（如分隔线）则 True"""
    if len(text) == 0:
        return False
    alpha_count = len([char for char in text if char.strip() and char.isalpha()])
    total_count = len([char for char in text if char.strip()])
    try:
        return (alpha_count / total_count) < threshold
    except:
        return False

def is_possible_title(
        text: str,
        title_max_word_length: int = 20,
        non_alpha_threshold: float = 0.5,
) -> bool:
    """判断文本是否是一个合法的标题"""
    if len(text) == 0:
        return False
    # 结尾有标点 → 不是标题
    if re.search(r"[^\w\s]\Z", text):
        return False
    # 文本太长 → 不是标题
    if len(text) > title_max_word_length:
        return False
    # 非字母占比太高 → 不是标题
    if under_non_alpha_ratio(text, threshold=non_alpha_threshold):
        return False
    # 以逗号句号结尾 → 不是标题
    if text.endswith((",", ".", "\uff0c", "\u3002")):
        return False
    # 全数字 → 不是标题
    if text.isnumeric():
        return False
    # 前5个字符中没有数字 → 不是标题（如"第一章"）
    text_5 = text[:5] if len(text) >= 5 else text
    if not any(c.isnumeric() for c in text_5):
        return False
    return True

def zh_title_enhance(docs: List[Document]) -> List[Document]:
    """
    标题增强：
    1. 遍历所有 chunk，标记哪个是标题
    2. 把标题文本拼到后续 chunk 内容前面，为每个块补充上下文
    """
    title = None
    if len(docs) > 0:
        for doc in docs:
            if is_possible_title(doc.page_content):
                doc.metadata['category'] = 'cn_Title'
                title = doc.page_content
            elif title:
                doc.page_content = f"下文与({title})有关。{doc.page_content}"
        return docs
    else:
        print("文档为空")
        return docs

# ==================== 3. 加载 + 切分 ====================
CHUNK_SIZE = 250     # 每块最多 250 字符
CHUNK_OVERLAP = 50   # 相邻块重叠 50 字符
ZH_TITLE_ENHANCE = True  # 是否开启标题增强

def load_and_split_documents(folder: str) -> List[Document]:
    """
    从文件夹加载文档，使用 ChineseRecursiveTextSplitter 切分，
    并可开启标题增强，把标题信息注入到每个 chunk 中。
    """
    text_splitter = ChineseRecursiveTextSplitter(
        keep_separator=True,
        is_separator_regex=True,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )

    all_chunks = []
    for file_path in Path(folder).iterdir():
        if file_path.is_file() and file_path.suffix in {".txt", ".md"}:
            # 读取文件，自动处理 BOM
            content = file_path.read_text(encoding="utf-8-sig")
            doc = Document(page_content=content, metadata={"source": file_path.name})

            # 切分
            chunks = text_splitter.split_documents([doc])

            # 标题增强
            if ZH_TITLE_ENHANCE:
                chunks = zh_title_enhance(chunks)

            # 标注序号
            for i, chunk in enumerate(chunks):
                chunk.metadata["chunk"] = i
                chunk.metadata["source"] = file_path.name

            all_chunks.extend(chunks)
            print(f"  [LOAD] {file_path.name} ({len(content)} 字) → 切成 {len(chunks)} 块")

    return all_chunks

# ==================== 4. 加载或构建索引 ====================
if os.path.exists(INDEX_PATH) and os.path.exists(DOCS_PATH):
    print("[OK] 从磁盘加载已有索引...")
    index = faiss.read_index(INDEX_PATH)
    with open(DOCS_PATH, "r", encoding="utf-8") as f:
        doc_dicts = json.load(f)
    documents = [Document(page_content=d["content"], metadata=d.get("metadata", {}))
                 for d in doc_dicts]
    print(f"[OK] 加载完成：{index.ntotal} 个文档块")
else:
    print(f"[INFO] 未找到索引，从 {DOCS_DIR} 加载并切分文档...")
    documents = load_and_split_documents(DOCS_DIR)

    texts = [doc.page_content for doc in documents]
    embeddings = embed_texts(texts)

    index = faiss.IndexFlatIP(len(embeddings[0]))
    index.add(np.array(embeddings, dtype=np.float32))

    faiss.write_index(index, INDEX_PATH)
    doc_dicts = [{"content": doc.page_content, "metadata": doc.metadata} for doc in documents]
    with open(DOCS_PATH, "w", encoding="utf-8") as f:
        json.dump(doc_dicts, f, ensure_ascii=False, indent=2)
    print(f"[OK] 构建完成：{index.ntotal} 个文档块 → {INDEX_PATH}")

# ==================== 5-6. 检索 + LLM ====================
query = "RAG如何解决幻觉问题？"
query_emb = embed_texts([query])[0]
scores, indices = index.search(np.array([query_emb], dtype=np.float32), k=3)

print("\n=== 检索结果 ===")
for i, (score, idx) in enumerate(zip(scores[0], indices[0])):
    if idx >= 0:
        meta = documents[idx].metadata
        category = meta.get("category", "")
        tag = f"[{category}]" if category else ""
        print(f"  [{i+1}] 分数: {score:.4f} {tag} | {meta['source']}[块{meta['chunk']}] | {documents[idx].page_content[:60]}...")

retrieved_docs = [documents[idx] for idx in indices[0] if idx >= 0]
context = "\n".join([doc.page_content for doc in retrieved_docs])

prompt = f"""根据以下已知信息，简洁和专业的来回答问题。
如果无法从中得到答案，请说"根据已知信息无法回答该问题"。

<已知信息>
{context}
</已知信息>

<问题>
{query}
</问题>"""

token = generate_token(API_KEY)
headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
data = {"model": "glm-4", "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7, "stream": False}

print("\n=== 调用 LLM 中... ===")
with httpx.Client(timeout=60) as client:
    response = client.post(CHAT_URL, headers=headers, json=data)
    response.raise_for_status()
    answer = response.json()["choices"][0]["message"]["content"]

print(f"\n=== LLM 回答 ===\n{answer}")
