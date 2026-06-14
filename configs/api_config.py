# API 密钥与服务地址
# 修改配置只需改这个文件，不用翻主逻辑代码

# ---- 智谱（Embedding + LLM） ----
ZHIPU_API_KEY = "f319167f721645fe91aa4918d321b521.bPLyCmwCzSOr1Ttb"
ZHIPU_EMBED_URL = "https://open.bigmodel.cn/api/paas/v4/embeddings"
ZHIPU_CHAT_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

# ---- 阿里云百炼（Rerank） ----
BAILIAN_API_KEY = "sk-2c906e393780490cac2a76b843e6aa4d"
BAILIAN_RERANK_URL = "https://dashscope.aliyuncs.com/compatible-api/v1/reranks"

# MySQL 连接配置
MYSQL_HOST = "localhost"
MYSQL_PORT = 3306
MYSQL_USER = "root"
MYSQL_PASSWORD = "123456"
MYSQL_DATABASE = "my_rag"

# Milvus 长期记忆向量库配置
MILVUS_URI = "http://127.0.0.1:19530"
MILVUS_MEMORY_COLLECTION = "long_term_memories"
