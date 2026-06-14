import json


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


def build_memory_summary_extract_prompt(conversation_text: str) -> str:
    return f"""请从最近几轮连续对话中提取值得沉淀的长期记忆。

长期记忆只保存跨会话仍然有用的信息，例如：
1. 用户身份、背景、学习阶段。
2. 用户长期偏好，例如希望解释更详细、喜欢某种技术栈。
3. 用户正在持续进行的项目、目标、约束。
4. 用户明确要求你以后记住的信息。

不要保存：
1. 一次性问题或临时任务。
2. 助手自己的推测。
3. 知识库文档里的通用知识。
4. 只在当前上下文里临时成立的信息。

提取要求：
1. 结合上下文理解，不要只看最后一句。
2. 如果多轮对话表达了同一件事，只输出一条精简后的记忆。
3. content 要完整、明确、短小，不要写成对话摘要。
4. 最多输出 3 条。

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

最近几轮对话：
{conversation_text[:4000]}"""


def build_memory_dedupe_prompt(candidate: dict, existing_memories: list[dict]) -> str:
    compact_memories = [
        {
            "id": memory.get("id"),
            "content": memory.get("content", ""),
            "category": memory.get("category", ""),
            "importance": memory.get("importance", 3),
        }
        for memory in existing_memories
    ]

    return f"""请判断候选长期记忆是否和已有长期记忆语义重复。

你只需要比较“候选记忆”和“已有记忆”是否表达同一件稳定信息，不要根据措辞是否完全相同来判断。

可选动作：
1. create：候选记忆是新的信息，已有记忆没有覆盖。
2. ignore：候选记忆已被已有记忆覆盖，不需要保存。
3. update：候选记忆和某条已有记忆说的是同一件事，但候选记忆更准确、更新或更完整，应该更新那条已有记忆。

规则：
1. 只有语义明确重复时才 ignore 或 update。
2. 如果候选记忆只是对已有记忆的小幅重复表达，选择 ignore。
3. 如果候选记忆能补充重要细节，选择 update，并返回要更新的 memory_id。
4. update 时 content 要写成合并后的完整记忆，不要只写增量。
5. 不确定时选择 create，避免误删用户信息。

只输出 JSON，不要输出 Markdown，不要解释。

输出格式：
{{
  "action": "create|ignore|update",
  "memory_id": null,
  "content": "最终要保存的长期记忆内容",
  "category": "profile|preference|project|goal|fact|general",
  "importance": 1
}}

候选记忆：
{json.dumps(candidate, ensure_ascii=False)}

已有记忆：
{json.dumps(compact_memories, ensure_ascii=False)}"""
