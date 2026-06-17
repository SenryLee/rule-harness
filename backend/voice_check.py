"""语态忠实度校验 — Harness §5 的辅助门。

防范的具体错误（华润测试中实测到的）：
  - 原文"保修金比例由发起人填写，**一般为** 3% 或 5%"
  - LLM 输出"保修金比例**不得低于** 3%，优选 5%"
                ↑↑↑↑↑ 软语态被升格为强义务

判定逻辑：
  - 原文使用软语态（"一般/通常/可/建议/示例..."）
  - 而 requirement 使用强义务词（"应/必须/不得/禁止..."）
  → 升格违规

v2.0 扩展：
  - 新增 neutral→strong 升格检测：原文无任何语态词，requirement 凭空使用禁止性义务
    （不得/严禁/禁止/不允许）→ 标记 voice_escalation_neutral
  - 校验范围从 requirement 扩展到 check_item + notes
  - 强指令词表新增"务必"

返回的失败项：
  - ``"voice_strong_for_soft_source"``：软语态原文 + 强义务 requirement
  - ``"voice_escalation_neutral"``：中性原文 + 凭空禁止性义务
"""
from __future__ import annotations


SOFT_VOICE_WORDS: frozenset[str] = frozenset({
    # 倾向性
    "一般", "通常", "原则上", "大多", "多为", "往往",
    # 弱建议 / 推荐
    "可", "建议", "不妨", "酌情", "酌定", "宜", "尽量", "推荐", "可参考",
    "可以", "参照", "参考",
    # 示例标识
    "示例", "举例", "比如", "例如",
    # 限定性
    "一般为", "酌情考虑", "按填写",
})

STRONG_VOICE_WORDS: frozenset[str] = frozenset({
    "应当", "必须", "应该", "应予", "应",
    "不得", "禁止", "不允许", "不可", "无权", "严禁", "务必",
})

# v2.0: 禁止性义务词——原文完全没有语态词时，requirement 不应凭空使用这些词
PROHIBITION_WORDS: frozenset[str] = frozenset({
    "不得", "严禁", "禁止", "不允许",
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


def check_voice_match(
    source_excerpt: str,
    requirement: str,
    check_item: str = "",
    notes: str = "",
) -> list[str]:
    """返回 [] 表示语态匹配；否则返回失败项列表。

    v2.0 扩展：
      1. soft→strong：原文软语态 + requirement 强义务 → ``voice_strong_for_soft_source``
      2. neutral→strong：原文中性 + requirement 含禁止性义务词 → ``voice_escalation_neutral``
      3. 校验范围：requirement + check_item + notes（合并检测）
    """
    src_voice = detect_voice(source_excerpt)
    # v2.0: 合并 requirement + check_item + notes 做语态检测
    combined_req = f"{requirement} {check_item} {notes}"
    req_voice = detect_voice(combined_req)

    failures: list[str] = []

    # 检测 1: soft → strong 升格
    if src_voice == "soft" and req_voice == "strong":
        failures.append("voice_strong_for_soft_source")

    # v2.0 检测 2: neutral → strong 升格（仅限禁止性义务词）
    # 原文完全无语态词（neutral），requirement 凭空使用"不得/严禁/禁止/不允许"
    if src_voice == "neutral":
        has_prohibition = any(word in combined_req for word in PROHIBITION_WORDS)
        if has_prohibition:
            failures.append("voice_escalation_neutral")

    return failures
