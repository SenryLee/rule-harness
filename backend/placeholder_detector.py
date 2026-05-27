"""占位符识别 + 占位规则判定 — 用于把"虚胖"规则从主输出中剥离。

实测华润手册中约 7% 的规则在 ``notes`` 里坦承"占位/无具体内容/需进一步补充"。
这类规则数量上让产出看起来丰富，但信号价值为 0，且会拉低审核员对全表的信任。

本模块给两个能力：
  1. :func:`detect_placeholders` — 扫一段文本是否含占位符模式
  2. :func:`is_placeholder_rule` — 判断一条候选规则是否属于"占位规则"，应进
     ``placeholders.csv`` 而非 ``main.csv``
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_PLACEHOLDER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"【[^】]{0,30}】"), "bracket"),
    (re.compile(r"[XxXx]{1,3}\s*[天日周月年]"), "xx_time"),
    (re.compile(r"_{1,}\s*%"), "underscore_pct"),
    (re.compile(r"(?:^|[\s,，。])[XxXx]\s*%"), "x_pct"),
    (re.compile(r"\s/\s|^\s*/\s*$"), "slash"),
    (re.compile(r"待填写|经办人填写|按实际填写|按各.{0,4}填写|按填写"), "literal_placeholder"),
]


@dataclass(frozen=True)
class PlaceholderSpan:
    start: int
    end: int
    kind: str
    text: str


def detect_placeholders(text: str) -> list[PlaceholderSpan]:
    """返回文本中所有命中的占位符片段。"""
    if not text:
        return []
    spans: list[PlaceholderSpan] = []
    for pat, kind in _PLACEHOLDER_PATTERNS:
        for m in pat.finditer(text):
            spans.append(PlaceholderSpan(
                start=m.start(),
                end=m.end(),
                kind=kind,
                text=m.group(0),
            ))
    spans.sort(key=lambda s: s.start)
    return spans


# ---------------------------------------------------------------------------
# 规则级判定
# ---------------------------------------------------------------------------

_PLACEHOLDER_KEYWORDS_IN_NOTES = (
    "占位",
    "无具体内容",
    "需进一步补充",
    "待补充",
    "此规则为占位",
    "原文未提供",
    "原文仅标题",
    "原文仅分类",
    "需结合具体条款",
)


def is_placeholder_rule(
    *,
    requirement: str,
    notes: str,
    threshold_type: str,
    self_confidence: float,
    source_excerpt: str = "",
    low_confidence_threshold: float = 0.4,
) -> bool:
    """判断一条规则是否为"占位规则"。

    满足以下任一即视为占位：
      1. ``threshold_type == "占位"``
      2. ``self_confidence`` 低于阈值（默认 0.4）
      3. ``notes`` 或 ``requirement`` 中含占位关键词集合
      4. 原文片段大段命中占位符模式，但规则仍硬给了 threshold
    """
    if (threshold_type or "").strip() == "占位":
        return True
    if self_confidence < low_confidence_threshold:
        return True

    blob = (notes or "") + "\n" + (requirement or "")
    for kw in _PLACEHOLDER_KEYWORDS_IN_NOTES:
        if kw in blob:
            return True

    # 边界条件：原文几乎全是占位（命中密度高），但规则装作有具体数值
    if source_excerpt:
        spans = detect_placeholders(source_excerpt)
        if spans and threshold_type and threshold_type != "占位":
            placeholder_chars = sum(s.end - s.start for s in spans)
            if len(source_excerpt) > 0 and placeholder_chars / len(source_excerpt) > 0.15:
                return True

    return False
