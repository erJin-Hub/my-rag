def build_conversation_title_prompt(query: str, answer: str, max_chars: int) -> str:
    return f"""根据首轮对话内容生成一个简短的会话标签名，风格参考 DeepSeek 的左侧会话标题。
要求：
1. 抽象概括用户真正想做的事，不要直接截断原问题。
2. 中文优先，最多 {max_chars} 个字。
3. 不要输出引号、句号、冒号、编号、表情。
4. 不要使用"会话""问题""关于"等空泛词。
5. 只输出标签名本身。

用户首问：
{query}

助手首答：
{answer[:1200]}"""
