def build_memory_extract_prompt(query: str, answer: str) -> str:
    return f"""请从本轮对话中判断是否需要沉淀为长期记忆。

长期记忆只保存跨会话仍然有用的信息，例如：
1. 用户身份、背景、学习阶段。
2. 用户长期偏好，例如希望解释更详细、喜欢某种技术栈。
3. 用户正在持续进行的项目、目标、约束。
4. 用户明确要求你以后记住的信息。

不要保存：
1. 一次性问题或临时任务。
2. 助手自己的推测。
3. 知识库文档里的通用知识。
4. 已经过时、含糊、无法确定的信息。

只输出 JSON，不要输出 Markdown，不要解释。
如果没有值得保存的长期记忆，输出：
{{"memories":[]}}

输出格式：
{{
  "memories": [
    {{
      "content": "一句完整、明确的长期记忆",
      "category": "profile|preference|project|goal|fact|general",
      "importance": 1
    }}
  ]
}}

importance 取值 1 到 5，5 表示非常重要。

用户本轮问题：
{query}

助手本轮回答：
{answer[:1500]}"""
