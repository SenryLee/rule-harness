"""语态忠实度校验 — Harness §5 的辅助门。

防范的具体错误（华润测试中实测到的）：
  - 原文"保修金比例由发起人填写，**一般为** 3% 或 5%"
  - LLM 输出"保修金比例**不得低于** 3%，优选 5%"
                ↑↑↑↑↑ 软语态被升格为强义务

判定逻辑：
  - 原文使用软语态（"一般/通常/可/建议/示例..."）
  - 而 requirement 使用强义务词（"应/必须/不得/禁止..."）
  → 升格违规

返回的失败项目前只有一种：``"voice_strong_for_soft_source"``。
"""
from __future__ import annotations


SOFT_VOICE_WORDS: frozenset[str] = frozenset({
    # 倾向性
    "一般", "通常", "原则上", "大多", "多为", "往往",
    # 弱建议 / 推荐
    "可", "建议", "不妨", "酌情", "酌定", "宜", "尽量", "推荐", "可参考",
    # 示例标识
    "示例", "举例", "比如", "例如",
    # 限定性
    "一般为", "参考", "酌情考虑", "按填写",
})

STRONG_VOICE_WORDS: frozenset[str] = frozenset({
    "应当", "必须", "应该", "应予", "应",
    "不得", "禁止", "不允许", "不可", "无权", "严禁",
})


def detect_voice(text: str) -> str:
    """返回 'strong' / 'soft' / 'neutral'。

    混合时倾向 ``soft``，因为这种场景下原文不是硬约束。
    """
    if not text:
        return "neutral"
    has_soft = any(word in text for word in SOFT_VOICE_WORDS)
    has_strong = any(word in text for word in STRONG_VOICE_WORDS)
    if has_soft and not has_strong:
        return "soft"
    if has_strong and not has_soft:
        return "strong"
    if has_soft and has_strong:
        # 软优先（更保守）
        return "soft"
    return "neutral"


def check_voice_match(source_excerpt: str, requirement: str) -> list[str]:
    """返回 [] 表示语态匹配；否则返回失败项列表。"""
    src = detect_voice(source_excerpt)
    req = detect_voice(requirement)
    if src == "soft" and req == "strong":
        return ["voice_strong_for_soft_source"]
    return []
