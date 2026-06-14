# 模型与切分参数
# 所有"可调的超参数"统一放这里

# ---- 文本切分 ----
CHUNK_SIZE = 250          # 每块最大字符数
CHUNK_OVERLAP = 50        # 相邻块重叠字符数
ZH_TITLE_ENHANCE = True   # 是否开启中文标题增强

# ---- Embedding ----
EMBEDDING_MODEL = "embedding-2"
EMBEDDING_DIM = 1024

# ---- LLM ----
LLM_MODEL = "glm-4"
TEMPERATURE = 0.7

# ---- 检索 ----
SEARCH_TOP_K = 10         # FAISS 粗排捞多少个候选
RERANK_TOP_N = 3          # 精排后保留多少个
MEMORY_VECTOR_TOP_K = 5   # 长期记忆向量检索保留多少条
