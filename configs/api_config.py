# API 密钥与服务地址
# 优先从项目根目录 .env 读取，避免把密钥写死在代码里。

from .env_loader import get_env, get_int_env

# ---- 智谱（Embedding + LLM） ----
ZHIPU_API_KEY = get_env("ZHIPU_API_KEY")
ZHIPU_EMBED_URL = get_env("ZHIPU_EMBED_URL", "https://open.bigmodel.cn/api/paas/v4/embeddings")
ZHIPU_CHAT_URL = get_env("ZHIPU_CHAT_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions")

# ---- 阿里云百炼（Rerank） ----
BAILIAN_API_KEY = get_env("BAILIAN_API_KEY")
BAILIAN_RERANK_URL = get_env("BAILIAN_RERANK_URL", "https://dashscope.aliyuncs.com/compatible-api/v1/reranks")

# ---- MySQL ----
MYSQL_HOST = get_env("MYSQL_HOST", "localhost")
MYSQL_PORT = get_int_env("MYSQL_PORT", 3306)
MYSQL_USER = get_env("MYSQL_USER", "root")
MYSQL_PASSWORD = get_env("MYSQL_PASSWORD")
MYSQL_DATABASE = get_env("MYSQL_DATABASE", "my_rag")

# ---- Milvus ----
MILVUS_URI = get_env("MILVUS_URI", "http://127.0.0.1:19530")
MILVUS_MEMORY_COLLECTION = get_env("MILVUS_MEMORY_COLLECTION", "long_term_memories")
