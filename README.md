# my-rag

`my-rag` 是一个用于学习和验证 RAG 工程化流程的 Python 项目。它从最基础的文档向量检索开始，逐步扩展到 FastAPI 服务、Web UI、短期对话历史、长期记忆、Milvus 记忆向量检索，以及基于 MCP 的联网搜索。

这个项目的定位不是直接替代 RAGFlow、Dify 这类平台，而是帮助自己理解一个 RAG 系统从脚本到服务化应用的完整链路。

## 当前能力

- 文档知识库：支持 `.txt`、`.md`、`.pdf`、`.docx` 上传和解析。
- 文本切分：使用中文递归切分规则，支持标题增强。
- 向量化：使用智谱 `embedding-2`。
- 知识库检索：使用 FAISS 做向量粗召回。
- 精排：使用阿里云百炼 `qwen3-rerank` 做 rerank。
- 对话服务：使用 FastAPI 提供普通问答、记忆问答和流式问答接口。
- 流式输出：通过 SSE 向前端逐步推送大模型回复。
- 短期记忆：MySQL 存储会话和消息历史。
- 长期记忆：MySQL 存储长期记忆，Milvus 存储长期记忆向量。
- 记忆检索：当前问题只 embedding 一次，同时复用于知识库 FAISS 和长期记忆 Milvus 检索。
- 记忆管理页面：支持新增、编辑、启用/禁用、搜索、筛选、分页。
- 联网搜索：通过 MCP Server 调用 Tavily Web Search。
- 前端页面：使用原生 HTML、CSS、JavaScript 实现聊天、知识库管理、长期记忆管理。

## 技术栈

- 后端：Python、FastAPI、Uvicorn
- 前端：原生 HTML / CSS / JavaScript
- 向量库：FAISS、Milvus
- 数据库：MySQL
- ORM：SQLAlchemy AsyncSession
- Embedding：智谱 `embedding-2`
- LLM：智谱 `glm-4`
- Rerank：阿里云百炼 `qwen3-rerank`
- MCP：`mcp` Python SDK
- Web Search：Tavily API
- 文档解析：`pypdf`、`python-docx`
- 文本切分：`langchain-text-splitters`

## 目录结构

```text
my-rag/
├── step11_web_ui.py              # 当前主入口，启动 FastAPI + Web UI
├── requirements.txt              # Python 依赖
├── README.md                     # 项目说明
├── configs/                      # 配置模块
│   ├── api_config.py             # API Key、MySQL、Milvus、MCP 等配置
│   ├── model_config.py           # 模型、切分、检索参数
│   ├── app_paths.py              # 项目路径配置
│   └── env_loader.py             # .env 加载工具
├── core/                         # RAG 底层能力
│   ├── embedding.py              # 智谱 embedding 调用
│   ├── indexer.py                # FAISS 构建、加载、检索
│   ├── splitter.py               # 文档加载和中文切分
│   ├── reranker.py               # 百炼 rerank
│   ├── document_loader.py        # txt/md/pdf/docx 文档解析
│   ├── memory_vector_store.py    # Milvus 长期记忆向量库
│   └── memory.py                 # 兼容旧调用的 memory facade
├── db/                           # 数据库层
│   ├── models.py                 # SQLAlchemy ORM 模型
│   └── session.py                # 异步数据库连接
├── repositories/                 # 数据访问层
│   ├── conversation_repository.py # 会话和历史消息 CRUD
│   └── memory_repository.py      # 长期记忆 CRUD、分页、向量同步
├── services/                     # 业务逻辑层
│   ├── chat_service.py           # RAG + 记忆 + MCP 搜索主链路
│   ├── conversation_service.py   # 会话业务
│   ├── document_service.py       # 文档上传和入库
│   ├── memory_service.py         # 长期记忆管理业务
│   └── mcp_search_service.py     # MCP Web Search 客户端
├── routers/                      # FastAPI 路由
│   ├── chat_router.py            # 聊天接口
│   ├── conversation_router.py    # 会话接口
│   ├── document_router.py        # 文档接口
│   ├── memory_router.py          # 长期记忆接口
│   └── page_router.py            # 页面路由
├── prompts/                      # Prompt 模板
│   ├── rag_prompts.py            # RAG / 记忆 / 联网搜索 prompt
│   ├── memory_prompts.py         # 长期记忆提取、总结、去重 prompt
│   └── conversation_prompts.py   # 会话标题生成 prompt
├── web/                          # 前端页面
│   ├── index.html                # 聊天页面
│   ├── app.js                    # 聊天页逻辑
│   ├── documents.html            # 知识库管理页
│   ├── documents.js              # 知识库页面逻辑
│   ├── memories.html             # 长期记忆管理页
│   ├── memories.js               # 长期记忆页面逻辑
│   └── styles.css                # 全局样式
├── mcp_servers/
│   └── web_search_server.py      # MCP Web Search Server
├── docs/                         # 知识库原始文档
├── data/                         # FAISS 索引和 documents.json，运行后生成
└── steps/                        # step1-step10 学习脚本
```

## 核心流程

### 1. 文档入库流程

```text
上传文档
-> 判断文件类型
-> 解析成纯文本
-> 中文递归切分
-> 可选标题增强
-> 调用 embedding-2 生成向量
-> 写入 FAISS
-> 持久化 faiss.index 和 documents.json
```

相关代码：

- `services/document_service.py`
- `core/document_loader.py`
- `core/splitter.py`
- `core/embedding.py`
- `core/indexer.py`

### 2. 普通 RAG 问答流程

```text
用户问题
-> query 转 embedding
-> FAISS 粗召回 top_k 文档块
-> 百炼 rerank 精排
-> 过滤低分文档
-> 拼接知识库上下文
-> 调用 glm-4
-> 返回答案和 Sources
```

### 3. 带记忆的流式问答流程

当前主要聊天接口走的是：

```text
POST /api/chat/memory/stream
```

流程如下：

```text
用户问题
-> 获取 conversation_id，没有则创建新会话
-> 查询最近 history_len 条短期历史
-> query 只 embedding 一次
-> query_vector 同时用于：
   1. FAISS 知识库检索
   2. Milvus 长期记忆检索
-> 知识库结果 rerank
-> 长期记忆按相似度过滤
-> 如果前端启用联网搜索，则通过 MCP 调 Tavily
-> 拼接 system prompt
-> glm-4 流式输出
-> 保存 user / assistant 消息
-> 首轮自动生成会话标题
-> 按规则或轮次自动提取长期记忆
```

这个流程的核心实现是：

- `services/chat_service.py`
- `prompts/rag_prompts.py`
- `repositories/conversation_repository.py`
- `repositories/memory_repository.py`

## 记忆系统

项目里有两类记忆。

### 短期记忆

短期记忆就是当前会话的历史消息，存储在 MySQL 的 `messages` 表中。

当前传给模型的是最近 `history_len` 条消息，默认 10 条。

注意：这里的 10 条是 10 条 message，不是 10 轮对话。一轮通常包含：

```text
user 一条
assistant 一条
```

所以 10 条大约是最近 5 轮。

### 长期记忆

长期记忆用于保存跨会话仍然有价值的信息，例如：

- 用户身份
- 用户偏好
- 项目背景
- 长期目标
- 稳定事实

长期记忆有两份存储：

```text
MySQL memories 表：存原始文本、分类、重要度、状态、来源会话
Milvus：存长期记忆向量，用于语义检索
```

聊天时会根据当前 query 的向量去 Milvus 找相关长期记忆，只把相关记忆放进 prompt，不再每次塞前 20 条。

### 自动提取长期记忆

当用户表达明显需要记住的信息时，会触发长期记忆提取，例如：

- “记住……”
- “你要记得……”
- “以后……”
- “我叫……”
- “我的项目……”
- “我的目标……”

另外，每隔一定轮次会对最近几轮对话做总结提取。

相关配置在：

```text
services/chat_service.py
MEMORY_SUMMARY_INTERVAL = 6
MEMORY_SUMMARY_WINDOW = 8
```

### 语义去重和更新

新增长期记忆前，会和同类型已有记忆做语义比较，让模型判断：

```text
create：新信息，新增
ignore：已有记忆已覆盖，忽略
update：和旧记忆表达同一件事，但新信息更准确，更新旧记忆
```

相关 prompt 在：

```text
prompts/memory_prompts.py
```

## MCP 联网搜索

项目中已经接入 MCP Web Search。

前端聊天页有“联网搜索”开关。开启后，本轮请求会带：

```json
{
  "enable_web_search": true
}
```

后端会通过：

```text
services/mcp_search_service.py
-> stdio 启动 mcp_servers/web_search_server.py
-> 调用 web_search 工具
-> Tavily API 搜索网页
-> 返回 title/url/snippet
```

搜索结果会被拼进 prompt 的 `<联网搜索结果>` 区块。模型如果使用联网搜索结果，需要在回答中用 `[1]`、`[2]` 这样的编号引用来源。

前端会把网页来源渲染成卡片。

## 前端页面

### 对话页

访问：

```text
http://127.0.0.1:8000/
```

功能：

- 新建对话
- 打开历史会话
- 删除会话
- 流式聊天
- 展示知识库 Sources
- 展示本轮命中的长期记忆
- 展示联网搜索来源
- 支持联网搜索开关

### 知识库页面

访问：

```text
http://127.0.0.1:8000/documents
```

功能：

- 上传 `.txt` / `.md` / `.pdf` / `.docx`
- 拖拽上传
- 查看当前知识库文件列表
- 查看每个文件切分出的 chunk 数

### 长期记忆页面

访问：

```text
http://127.0.0.1:8000/memories
```

功能：

- 新建长期记忆
- 编辑长期记忆
- 启用 / 禁用长期记忆
- 按类型筛选
- 按关键词模糊搜索
- 支持包含禁用记忆
- 服务端分页
- 每页条数可选：5 / 10 / 15 / 20 / 30 / 50
- 显示来源会话、创建时间、更新时间、启用状态

关键词搜索当前是数据库字符串模糊搜索，不是语义搜索。搜索字段包括：

- `content`
- `category`
- `source_conversation_id`

## 后端接口

### 聊天接口

```text
POST /api/chat
```

普通 RAG 问答，不带记忆。

```text
POST /api/chat/memory
```

带短期历史、长期记忆、可选联网搜索的非流式问答。

```text
POST /api/chat/memory/stream
```

当前前端主要使用的接口，带短期历史、长期记忆、可选联网搜索，使用 SSE 流式返回。

请求示例：

```json
{
  "query": "RAG 是什么？",
  "conversation_id": "",
  "history_len": 10,
  "enable_web_search": false
}
```

### 会话接口

```text
POST /api/conversations/new
GET /api/conversations
GET /api/conversations/{conversation_id}/history
DELETE /api/conversations/{conversation_id}
```

### 文档接口

```text
POST /api/documents/upload
GET /api/documents/list
```

### 长期记忆接口

```text
POST /api/memories
GET /api/memories
PUT /api/memories/{memory_id}
DELETE /api/memories/{memory_id}
POST /api/memories/vector-sync
```

`GET /api/memories` 支持：

```text
include_disabled
category
keyword
limit
page
```

返回结构包含：

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 5,
  "total_pages": 1
}
```

## 配置说明

项目优先从根目录 `.env` 读取配置。

建议创建 `.env`：

```env
# 智谱
ZHIPU_API_KEY=你的智谱API_KEY
ZHIPU_EMBED_URL=https://open.bigmodel.cn/api/paas/v4/embeddings
ZHIPU_CHAT_URL=https://open.bigmodel.cn/api/paas/v4/chat/completions

# 阿里云百炼
BAILIAN_API_KEY=你的百炼API_KEY
BAILIAN_RERANK_URL=https://dashscope.aliyuncs.com/compatible-api/v1/reranks

# MySQL
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=你的MySQL密码
MYSQL_DATABASE=my_rag

# Milvus
MILVUS_URI=http://127.0.0.1:19530
MILVUS_MEMORY_COLLECTION=long_term_memories

# MCP Web Search
MCP_SEARCH_COMMAND=python
MCP_SEARCH_SCRIPT=mcp_servers/web_search_server.py
MCP_SEARCH_TOOL=web_search
TAVILY_API_KEY=你的Tavily_API_KEY
TAVILY_SEARCH_URL=https://api.tavily.com/search
```

模型和检索参数在：

```text
configs/model_config.py
```

当前主要参数：

```python
CHUNK_SIZE = 250
CHUNK_OVERLAP = 50
EMBEDDING_MODEL = "embedding-2"
EMBEDDING_DIM = 1024
LLM_MODEL = "glm-4"
TEMPERATURE = 0.7
SEARCH_TOP_K = 10
RERANK_TOP_N = 3
RERANK_MIN_SCORE = 0.35
MEMORY_VECTOR_TOP_K = 5
MEMORY_MIN_SCORE = 0.3
```

## 启动方式

### 1. 创建虚拟环境

Windows PowerShell：

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
```

### 2. 安装依赖

```powershell
pip install -r requirements.txt
```

如果网络较慢，可以使用国内镜像：

```powershell
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 3. 准备外部服务

需要准备：

- MySQL
- Milvus
- 智谱 API Key
- 阿里云百炼 API Key
- 如果使用联网搜索，还需要 Tavily API Key

### 4. 启动项目

```powershell
python step11_web_ui.py
```

启动成功后访问：

```text
http://127.0.0.1:8000/
```

接口文档：

```text
http://127.0.0.1:8000/docs
```

## 数据存储

### 本地文件

```text
docs/                 原始知识库文档
data/faiss.index      FAISS 向量索引
data/documents.json   chunk 文本和 metadata
```

### MySQL

当前 ORM 模型在：

```text
db/models.py
```

主要表：

```text
conversations   会话
messages        会话消息
memories        长期记忆
```

### Milvus

Milvus collection：

```text
long_term_memories
```

默认向量维度：

```text
1024
```

因为使用的是智谱 `embedding-2`。

## 当前设计上的取舍

### 为什么不用 LangChain 全家桶

项目只用了 `langchain-text-splitters` 和 `langchain_core.documents.Document`，没有使用 LangChain 的完整 RAG Chain。

原因是这个项目的学习目标是拆开理解每一步：

```text
文档解析
切分
embedding
FAISS
rerank
prompt 拼接
LLM 调用
history 管理
长期记忆
FastAPI 服务
前端交互
MCP 工具调用
```

如果直接用框架封装好的 Chain，学习成本会降低，但很多底层细节不容易看清。

### 为什么长期记忆不用 LangChain Memory

当前做法是生产系统中更常见的方式：

```text
历史消息存在数据库
长期记忆单独建表
长期记忆向量化后进入向量库
每轮对话按相关性检索需要的记忆
```

LangChain Memory 更适合快速原型；真正的业务系统通常会自己管理历史、摘要、长期记忆、权限和数据结构。

### 为什么 MCP 搜索是可选开关

联网搜索会增加：

- 请求耗时
- 外部 API 成本
- 搜索结果不稳定性
- prompt 噪音

所以默认不启用，只有需要最新信息时手动开启。

## 已完成的学习阶段

```text
step1  最简 RAG
step2  FAISS 持久化
step3  加载 docs 文件夹
step4  文本切分
step5  中文切分和标题增强
step6  Reranker 精排
step7  配置系统重构
step7.5 模块拆分
step8  FastAPI 服务
step9  SSE 流式输出
step10 对话记忆
step11 Web UI、多格式文档、长期记忆、MCP 搜索
```

## 后续可优化方向

- 检索调试页面：展示 FAISS 候选、rerank 分数、长期记忆命中、联网搜索结果。
- 上传安全：限制文件大小、安全文件名、避免路径穿越、避免重复覆盖。
- 文档删除和重建索引：当前支持上传和追加，还需要补删除/重建能力。
- PDF 解析增强：`pypdf` 对部分 PDF 可能失败，可以考虑增加 PyMuPDF 兜底。
- 长期记忆同步状态：增加 `synced_at`、`vector_version`、`sync_status`。
- MCP 搜索性能：当前每次通过 stdio 启动 MCP server，后续可以考虑常驻服务或连接复用。
- 耗时日志：记录 embedding、FAISS、rerank、Milvus、Web Search、LLM 首 token 耗时。
- 权限和安全：如果后续开放 MCP 文件/命令工具，需要沙箱和权限控制。
- README 和代码注释持续同步。

## AI 上下文区块

下面这段可以在新会话里直接发给 AI，让 AI 快速理解这个项目背景。

```text
你现在正在协助我开发一个 Python RAG 学习项目，项目名是 my-rag，路径是 D:\gcj\code\my-rag。

项目定位：
这是一个用于学习 RAG 工程化流程的项目，不是直接使用 RAGFlow/Dify 这类平台。目标是从底层理解文档解析、切分、embedding、FAISS、rerank、prompt、LLM、history、长期记忆、FastAPI、Web UI、MCP 工具调用等完整链路。

当前主入口：
step11_web_ui.py

当前页面：
- /：聊天页面
- /documents：知识库管理页面
- /memories：长期记忆管理页面
- /docs：FastAPI 接口文档

当前技术栈：
- 后端：Python + FastAPI + Uvicorn
- 前端：原生 HTML/CSS/JavaScript
- Embedding：智谱 embedding-2，维度 1024
- LLM：智谱 glm-4
- Rerank：阿里云百炼 qwen3-rerank
- 知识库向量库：FAISS
- 长期记忆向量库：Milvus
- 业务数据库：MySQL
- ORM：SQLAlchemy AsyncSession
- MCP：Python mcp SDK
- 联网搜索：MCP Server 调 Tavily API

核心链路：
用户提问后，系统查询短期历史，然后对 query 只做一次 embedding。这个 query vector 同时用于 FAISS 知识库检索和 Milvus 长期记忆检索。知识库检索结果会经过百炼 rerank，并用 RERANK_MIN_SCORE 过滤低分文档。长期记忆会用 MEMORY_MIN_SCORE 过滤低相似度结果。如果前端勾选“联网搜索”，后端会通过 MCP 调用 Tavily 搜索，并把搜索结果放进 prompt。最后调用 glm-4 流式输出，并保存对话历史，必要时自动提取/更新长期记忆。

重要目录：
- configs/：配置
- core/：embedding、FAISS、splitter、reranker、document_loader、Milvus memory vector store
- db/：SQLAlchemy models 和 session
- repositories/：数据库访问层
- services/：业务逻辑层
- routers/：FastAPI 路由
- prompts/：prompt 模板
- web/：前端页面
- mcp_servers/：MCP Server
- steps/：之前 step1-step10 的学习脚本

关键文件：
- services/chat_service.py：RAG + 短期历史 + 长期记忆 + MCP 搜索主链路
- core/indexer.py：FAISS 索引和检索，包含 search_by_vector
- core/memory_vector_store.py：Milvus 长期记忆向量检索，包含 search_memory_hits_by_vector
- repositories/memory_repository.py：长期记忆 CRUD、分页、命中分数合并、向量同步
- prompts/rag_prompts.py：RAG、长期记忆、联网搜索 system prompt
- web/app.js：聊天页逻辑
- web/memories.js：长期记忆管理页逻辑

当前已经实现：
- 文档上传：txt/md/pdf/docx
- 文档解析、切分、embedding、FAISS 持久化
- RAG 检索和 rerank
- FastAPI 接口
- SSE 流式输出
- MySQL 会话历史
- MySQL 长期记忆
- Milvus 长期记忆向量检索
- 长期记忆自动提取、总结、语义去重、更新
- 长期记忆管理页面：新增、编辑、启用/禁用、搜索、筛选、分页
- MCP Web Search：通过 Tavily 搜索
- 前端展示知识库 Sources、命中长期记忆、联网搜索来源

当前注意点：
- .env 中配置 ZHIPU_API_KEY、BAILIAN_API_KEY、MYSQL_PASSWORD、MILVUS_URI、TAVILY_API_KEY 等。
- 当前 README 说明应保持和代码同步。
- 不要把 API Key 写死进代码。
- 上传文档目前还需要进一步加强安全：文件大小限制、安全文件名、重复文件处理。
- MCP 搜索当前通过 stdio 启动 server，可能有启动开销。
- vector-sync 是全量同步长期记忆向量，数据多时不适合频繁调用。
- 如果优化性能，优先加耗时日志，观察 embedding、FAISS、rerank、Milvus、Web Search、LLM 首 token 耗时。

协作方式：
请优先阅读当前代码再建议修改。改代码时保持现有分层：router 只放入口，service 放业务逻辑，repository 放数据库访问，core 放底层能力，prompt 放 prompts/。前端保持原生 HTML/CSS/JS 风格。
```
