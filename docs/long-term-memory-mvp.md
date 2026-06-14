# 长期记忆 MVP

这一版先做最小可用长期记忆：重要信息写入 `memories` 表，聊天时读取启用的长期记忆并放进 system prompt。

## 和 history_len 的关系

`messages` 表保存完整聊天记录，`history_len` 控制每次只取最近多少条消息给模型，这是短期上下文窗口。

`memories` 表保存跨会话仍然有用的信息，例如用户身份、偏好、项目背景和长期目标。它不依赖当前会话，新的会话也能读取到。

长期记忆现在分两层存储：

```text
MySQL memories 表：存原文、分类、重要度、启用状态、时间等结构化信息。
Milvus long_term_memories collection：存 content 的 embedding 向量，用于按当前问题检索相关记忆。
```

## 数据流

```text
用户提问
-> 检索知识库文档
-> 对当前问题生成 embedding
-> 到 Milvus 检索相关长期记忆 memory_id
-> 回 MySQL 读取 enabled=True 的记忆原文
-> 读取当前会话最近 history_len 条消息
-> 拼成 messages 发给大模型
-> 保存本轮 user / assistant 消息
-> 代码判断本轮是否需要进入长期记忆提取
-> 命中规则时提取当前轮；每隔 N 轮时总结最近几轮
-> 让大模型判断是否值得沉淀长期记忆
-> 和同类型已有记忆做语义去重
-> 根据判断结果新增、忽略或更新 memories 表
```

## 记忆接口

新增长期记忆：

```bash
curl -X POST http://127.0.0.1:8000/api/memories \
  -H "Content-Type: application/json" \
  -d "{\"content\":\"用户是 RAG 学习新手，希望解释循序渐进。\",\"category\":\"preference\",\"importance\":5}"
```

查看长期记忆：

```bash
curl http://127.0.0.1:8000/api/memories
```

按分类查看长期记忆：

```bash
curl "http://127.0.0.1:8000/api/memories?category=preference"
```

查看已禁用记忆并限制返回数量：

```bash
curl "http://127.0.0.1:8000/api/memories?include_disabled=true&limit=50"
```

手动同步已有长期记忆到 Milvus：

```bash
curl -X POST http://127.0.0.1:8000/api/memories/vector-sync
```

编辑长期记忆：

```bash
curl -X PUT http://127.0.0.1:8000/api/memories/1 \
  -H "Content-Type: application/json" \
  -d "{\"content\":\"用户正在学习 RAG 长期记忆模块，希望解释代码时逐行讲解。\",\"category\":\"preference\",\"importance\":5,\"enabled\":true}"
```

禁用长期记忆：

```bash
curl -X DELETE http://127.0.0.1:8000/api/memories/1
```

## 第一版限制

- 删除接口实际是禁用，数据还在表里。
- 聊天时优先用 Milvus 按当前问题检索相关长期记忆；如果 Milvus 或 embedding 失败，会回退到默认读取重要度最高、最近更新的 20 条记忆。
- 自动提取已经做了轻量语义去重：先跳过完全相同内容，再让模型比较同类型已有记忆，决定新增、忽略或更新。
- 自动提取不是每轮都调用大模型，而是先用代码规则粗筛：命中关键词时提取当前轮；当前会话用户消息数达到 6 的倍数时，总结最近 8 轮。
- 语义去重仍然只比较同类型最近的 20 条记忆；Milvus 目前用于聊天时挑选相关长期记忆。

## Milvus 向量检索流程

保存或更新长期记忆时：

```text
写入 MySQL memories 表
-> 对 content 生成 embedding
-> upsert 到 Milvus long_term_memories
-> Milvus 里的主键 memory_id 对应 MySQL memories.id
```

聊天读取长期记忆时：

```text
用户 query
-> 生成 query embedding
-> Milvus 搜索相似记忆
-> 得到 memory_id 列表
-> 回 MySQL 查 enabled=True 的记忆内容
-> 拼进 system prompt
```

禁用长期记忆时：

```text
MySQL enabled=False
-> 删除 Milvus 中对应 memory_id 的向量
```

## 自动提取长期记忆

`/api/chat/memory/stream` 每次完整回答后，不会立刻调用大模型提取记忆，而是先走一层代码判断。

当前触发方式有三种：

```text
1. 用户手动保存：通过 /memories 页面或 POST /api/memories。
2. 规则触发：用户问题里出现“记住、以后、我叫、我是、我喜欢、我的项目、我的目标”等关键词。
3. 定期总结：同一个会话里，用户消息数达到 6 的倍数时，总结最近 8 轮对话。
```

可以记成：

```text
代码先粗筛，判断有没有必要花 token。
大模型再精判，判断具体要不要保存、保存什么。
```

## 定期总结策略

当前配置在 `services/chat_service.py`：

```python
MEMORY_SUMMARY_INTERVAL = 6
MEMORY_SUMMARY_WINDOW = 8
```

含义：

```text
每 6 轮触发一次总结，但每次读取最近 8 轮对话。
```

这样会形成滑动窗口：

```text
第 6 轮：总结第 1-6 轮
第 12 轮：总结第 5-12 轮
第 18 轮：总结第 11-18 轮
```

窗口比间隔大 2 轮，是为了保留一点重叠，避免重要信息刚好出现在两次总结的边界附近。

提取规则在 `prompts/memory_prompts.py`：

```text
保存：用户身份、偏好、项目背景、长期目标、明确要求记住的信息。
不保存：一次性问题、助手推测、知识库通用知识、含糊信息。
```

模型需要返回 JSON：

```json
{"memories":[{"content":"用户是 RAG 学习新手。","category":"profile","importance":4}]}
```

服务端会解析 JSON，限制分类和重要度，最多处理 3 条候选记忆。

保存前会做两层去重：

```text
候选记忆
-> 如果内容完全相同，直接跳过
-> 查询同类型已有记忆
-> 让大模型判断 create / ignore / update
-> create：新增一条记忆
-> ignore：已有记忆已经覆盖，不保存
-> update：更新某条已有记忆，避免越存越重复
```

后续可以继续做：给记忆加 embedding，按当前问题检索最相关的几条；再用向量相似度先筛出候选重复项，减少额外的大模型调用。
