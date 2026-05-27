"""数值忠实度校验 — Harness §5 的"第五重门"。

为什么需要这一门
----------------
LLM 抽取合同审核规则时极易"数值幻觉"：原文用 ``【】`` 占位或写"按各大区填写"，
模型却自作主张写出"不得超过 60 天"。这类规则一旦上线，会让审核员产生"看似有
依据实际无依据"的错误判断——比"没有规则"更危险。

本模块提供 :func:`validate_fidelity`，对每条候选规则做硬性校验：所有出现在
``requirement / check_item / notes`` 里的数字 token 都必须能在 ``source_excerpt``
里逐字找到（容忍标点、空格、全/半角差异）。

例外清单见 ``fidelity_exceptions.yaml``：常见的"两份""24 小时"等不参与校验。

调用方
------
:func:`backend.harness.validate_fidelity` 转发到这里；编排器
:func:`backend.orchestrator._finalize` 在 dedupe 之后调用。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml

_EXCEPTIONS_PATH = Path(__file__).resolve().parent / "fidelity_exceptions.yaml"

# ---------------------------------------------------------------------------
# 数字 token 正则
# ---------------------------------------------------------------------------

# 阿拉伯数字 + 中文单位 / 百分号
_NUMERIC_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\d+(?:\.\d+)?\s*%"),                          # 30% / 30.5%
    re.compile(r"\d+(?:\.\d+)?\s*[一-鿿]"),            # 5 天 / 30 万
    re.compile(r"\d+(?:\.\d+)?"),                              # 单纯数字 30
]

# 中文数字 + 单位
_CN_NUM_RX = re.compile(
    r"[一二两三四五六七八九十百千万亿零]+\s*"
    r"(?:[一-鿿%])"
)

# 用于规范化比对的正则
_PUNCT_RX = re.compile(r"[\s,，。．.;；:：、!！?？\"“”‘’()（）\[\]【】<>《》—\-]")


@dataclass(frozen=True)
class FidelityException:
    auto_skip_integers: int
    tokens: frozenset[str]
    patterns: tuple[re.Pattern[str], ...]


def _load_exceptions() -> FidelityException:
    if not _EXCEPTIONS_PATH.exists():
        return FidelityException(auto_skip_integers=2, tokens=frozenset(), patterns=())
    raw = yaml.safe_load(_EXCEPTIONS_PATH.read_text(encoding="utf-8")) or {}
    return FidelityException(
        auto_skip_integers=int(raw.get("auto_skip_integers", 2)),
        tokens=frozenset(str(t) for t in raw.get("tokens", []) or []),
        patterns=tuple(re.compile(p) for p in raw.get("patterns", []) or ()),
    )


EXCEPTIONS = _load_exceptions()


def _normalize(text: str) -> str:
    """规范化：NFKC 全角 → 半角 → 去标点空格。"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    return _PUNCT_RX.sub("", text)


def _is_excepted(token: str, span_text: str) -> bool:
    """token 是否在例外清单里跳过。

    判定顺序：
      1. 命中 ``tokens`` 字面集合 → 跳过
      2. 命中 ``patterns`` 正则 → 跳过
      3. 纯整数且 ≤ ``auto_skip_integers`` → 跳过
      4. 否则参与校验
    """
    if token in EXCEPTIONS.tokens:
        return True

    for pat in EXCEPTIONS.patterns:
        if pat.search(span_text):
            return True

    # 纯整数的情况
    if token.isdigit():
        try:
            if int(token) <= EXCEPTIONS.auto_skip_integers:
                return True
        except ValueError:
            pass

    return False


def _extract_tokens(text: str) -> list[str]:
    """从一段文本中抽出所有"数值 token"。

    优先匹配带单位的形式（30 天 / 30%），剩余裸数字按整体抓取，避免重复计入。
    """
    if not text:
        return []
    seen: list[tuple[int, int, str]] = []

    def _add(m: re.Match[str]) -> None:
        seen.append((m.start(), m.end(), m.group(0).strip()))

    for pat in _NUMERIC_PATTERNS:
        for m in pat.finditer(text):
            # 跳过被前一个更长 token 完全覆盖的 span
            if any(start <= m.start() and m.end() <= end for start, end, _ in seen):
                continue
            _add(m)

    for m in _CN_NUM_RX.finditer(text):
        if any(start <= m.start() and m.end() <= end for start, end, _ in seen):
            continue
        _add(m)

    seen.sort()
    return [tok for _, _, tok in seen]


def _grounded(token: str, normalized_excerpt: str) -> bool:
    """token 的规范化形式是否出现在原文规范化中。"""
    norm_tok = _normalize(token)
    if not norm_tok:
        return True  # 空 token 视为已 ground
    return norm_tok in normalized_excerpt


@dataclass(frozen=True)
class FidelityResult:
    passed: bool
    failures: tuple[str, ...]       # 不能 ground 的 token 列表
    grounded_tokens: tuple[str, ...]


def check_fidelity(
    requirement: str,
    check_item: str,
    notes: str,
    source_excerpt: str,
) -> FidelityResult:
    """对一条候选规则做忠实度校验。

    入参全部是已渲染的文本字段；调用方负责从 ``RuleCandidate`` 中取出对应值。

    返回的 ``failures`` 是无法在原文中 ground 的 token 字符串列表；空 → 通过。
    """
    norm_excerpt = _normalize(source_excerpt)
    failures: list[str] = []
    grounded: list[str] = []

    for field_text in (requirement, check_item, notes):
        for token in _extract_tokens(field_text):
            if _is_excepted(token, field_text):
                grounded.append(token)
                continue
            if _grounded(token, norm_excerpt):
                grounded.append(token)
            else:
                failures.append(token)

    return FidelityResult(
        passed=(len(failures) == 0),
        failures=tuple(failures),
        grounded_tokens=tuple(grounded),
    )


def is_low_severity(failures: tuple[str, ...]) -> bool:
    """单一不能 ground 的数字 → 低严重度（降级该规则，不丢）；≥2 → 高严重度（丢弃）。"""
    return 0 < len(failures) <= 1
