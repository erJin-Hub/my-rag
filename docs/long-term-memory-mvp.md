# 长期记忆 MVP

这一版先做最小可用长期记忆：重要信息写入 `memories` 表，聊天时读取启用的长期记忆并放进 system prompt。

## 和 history_len 的关系

`messages` 表保存完整聊天记录，`history_len` 控制每次只取最近多少条消息给模型，这是短期上下文窗口。

`memories` 表保存跨会话仍然有用的信息，例如用户身份、偏好、项目背景和长期目标。它不依赖当前会话，新的会话也能读取到。

## 数据流

```text
用户提问
-> 检索知识库文档
-> 读取 memories 表中 enabled=True 的长期记忆
-> 读取当前会话最近 history_len 条消息
-> 拼成 messages 发给大模型
-> 保存本轮 user / assistant 消息
-> 自动判断本轮对话是否值得沉淀长期记忆
-> 有价值就写入 memories 表
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
- 每次默认取重要度最高、最近更新的 20 条记忆。
- 自动提取只做了完全相同内容去重，还没有做语义相似去重。
- 还没有做记忆更新、合并和向量检索。

## 自动提取长期记忆

`/api/chat/memory/stream` 每次完整回答后，会额外调用一次大模型，让它判断本轮对话有没有值得长期保存的信息。

提取规则在 `prompts/memory_prompts.py`：

```text
保存：用户身份、偏好、项目背景、长期目标、明确要求记住的信息。
不保存：一次性问题、助手推测、知识库通用知识、含糊信息。
```

模型需要返回 JSON：

```json
{"memories":[{"content":"用户是 RAG 学习新手。","category":"profile","importance":4}]}
```

服务端会解析 JSON，限制分类和重要度，最多保存 3 条，并跳过完全重复的记忆。

后续可以继续做：给记忆加 embedding，按当前问题检索最相关的几条；再做语义去重、记忆更新和记忆合并。
