"""语义忠实度校验 — v2.0 新增的"第五重门半"。

为什么需要这一门
----------------
:mod:`backend.fidelity` 只校验数字 token，:mod:`backend.voice_check` 只校验
语态升格。两者都无法拦截"文字语义级幻觉"：

- 模型把原文"可参考"改写为"应当参考并提交董事会审议"（增编审查动作）
- 模型凭空引入原文未提及的法律术语（违约金、不可抗力、管辖法院）
- 模型编造原文没有的主体（"丙方"而原文只有甲乙双方）

本模块从 ``requirement / check_item`` 中提取**名词性关键短语**，校验是否能在
``source_excerpt`` 中找到。偏离率过高 → 降级或丢弃。

覆盖维度
--------
1. **法律术语**：违约金、不可抗力、管辖法院、争议解决、保密义务、知识产权、
   赔偿责任、连带责任、担保、质押、抵押、保险、审计、终止、解除、撤销等
2. **主体名词**：甲方/乙方/丙方/双方/各方/出租方/承租方/买方/卖方/委托方/受托方等
3. **数字+单位**：由 :func:`backend.fidelity.check_fidelity` 覆盖，此处不重复

调用方
------
:func:`backend.orchestrator._apply_fidelity_gate` 在 verify_excerpt + check_fidelity
之后调用，结果写入 ``RuleCandidate.semantic_pass / semantic_failures /
semantic_deviation``，并接入 :mod:`backend.confidence` 综合置信度。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# 词表
# ---------------------------------------------------------------------------

# 法律术语（按合同审查高频排序）。匹配时按词组长度降序，优先匹配长词。
_LEGAL_TERMS: tuple[str, ...] = (
    "不可抗力", "争议解决", "管辖法院", "违约责任", "连带责任", "赔偿责任",
    "违约金", "定金", "预付款", "保证金", "担保", "保证", "质押", "抵押",
    "留置", "保险", "审计", "终止", "解除", "撤销", "无效", "可撤销",
    "知识产权", "商业秘密", "保密义务", "竞业限制", "排他性", "独占",
    "优先购买权", "优先受让权", "回购", "对赌", "估值调整",
    "不可转让", "不得转让", "债权转让", "债务承担",
    "强制执行", "财产保全", "证据保全", "先予执行",
    "诉讼时效", "仲裁", "调解", "和解",
    "董事会", "股东会", "监事会", "法定代表人",
    "批准", "备案", "登记", "公告",
    "验收", "交付", "移交", "结算", "清算",
    "最高限额", "累计限额", "单笔限额",
    "工作日", "自然日", "法定节假日",
)

# 主体名词
_SUBJECT_NOUNS: tuple[str, ...] = (
    "甲方", "乙方", "丙方", "丁方", "戊方", "己方", "庚方", "辛方",
    "双方", "三方", "各方", "一方", "对方",
    "出租方", "承租方", "买方", "卖方", "委托方", "受托方",
    "发包方", "承包方", "许可方", "被许可方", "转让方", "受让方",
    "保证人", "被保证人", "抵押人", "抵押权人", "出质人", "质权人",
    "债权人", "债务人", "受益人", "管理人", "托管人",
)

# 规范化正则：去标点空格
_PUNCT_RX = re.compile(r"[\s,，。．.;；:：、!！?？\"“”‘’()（）\[\]【】<>《》—\-]")


def _normalize(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    return _PUNCT_RX.sub("", text)


@dataclass(frozen=True)
class SemanticResult:
    passed: bool
    failures: tuple[str, ...]       # 未能在 source_excerpt 中找到的关键短语
    deviation: float                # 偏离率 = failures / total
    total_phrases: int


def _extract_phrases(text: str) -> list[str]:
    """从文本中提取法律术语 + 主体名词（去重保序）。"""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    # 按词组长度降序匹配，优先捕获长词（如"争议解决"优先于"争议"）
    for term in sorted(_LEGAL_TERMS + _SUBJECT_NOUNS, key=len, reverse=True):
        if term in text and term not in seen:
            found.append(term)
            seen.add(term)
    return found


def check_semantic_fidelity(
    requirement: str,
    check_item: str,
    source_excerpt: str,
) -> SemanticResult:
    """对一条候选规则做语义忠实度校验。

    从 ``requirement + check_item`` 提取法律术语和主体名词，
    校验每个短语是否能在 ``source_excerpt`` 中找到（归一化后子串匹配）。

    返回 ``SemanticResult``：
      - ``failures``：未能在原文中找到的短语
      - ``deviation``：偏离率 = len(failures) / len(total_phrases)
      - ``passed``：deviation <= 0.4
    """
    combined = f"{requirement} {check_item}"
    phrases = _extract_phrases(combined)

    if not phrases:
        # 没有可校验的关键短语，视为通过（无法判定语义偏离）
        return SemanticResult(passed=True, failures=(), deviation=0.0, total_phrases=0)

    norm_excerpt = _normalize(source_excerpt)
    failures: list[str] = []

    for phrase in phrases:
        norm_phrase = _normalize(phrase)
        if not norm_phrase:
            continue
        if norm_phrase not in norm_excerpt:
            failures.append(phrase)

    deviation = len(failures) / len(phrases) if phrases else 0.0
    passed = deviation <= 0.4

    return SemanticResult(
        passed=passed,
        failures=tuple(failures),
        deviation=deviation,
        total_phrases=len(phrases),
    )


def should_discard(result: SemanticResult) -> bool:
    """偏离率 > 0.7 → 丢弃（output_target=discarded）。"""
    return result.deviation > 0.7
