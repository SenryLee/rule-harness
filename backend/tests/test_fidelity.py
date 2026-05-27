"""数值忠实度门 + 语态校验 + 占位识别的单测。"""
from __future__ import annotations

import pytest

from backend.fidelity import (
    EXCEPTIONS,
    FidelityResult,
    check_fidelity,
    _extract_tokens,
    _is_excepted,
    _normalize,
)
from backend.voice_check import check_voice_match, detect_voice
from backend.placeholder_detector import detect_placeholders, is_placeholder_rule


# ---------------------------------------------------------------------------
# 数字 token 抽取
# ---------------------------------------------------------------------------

class TestExtractTokens:
    def test_percent(self):
        tokens = _extract_tokens("不得超过 30%")
        assert "30%" in tokens or "30" in tokens

    def test_chinese_unit(self):
        tokens = _extract_tokens("不得低于 60 天")
        joined = " ".join(tokens)
        assert "60" in joined

    def test_multiple_numbers(self):
        tokens = _extract_tokens("3% 或 5%")
        assert any("3" in t for t in tokens)
        assert any("5" in t for t in tokens)

    def test_empty_text(self):
        assert _extract_tokens("") == []


# ---------------------------------------------------------------------------
# 例外清单
# ---------------------------------------------------------------------------

class TestExceptions:
    def test_small_integer_skipped(self):
        # 默认 ≤ 2 的纯整数视为常用泛指
        assert _is_excepted("2", "两份原件")

    def test_three_is_not_skipped(self):
        assert not _is_excepted("3", "保密期限 3 年")

    def test_known_const_skipped(self):
        # 24 小时 在例外清单里
        assert _is_excepted("24 小时", "24 小时内回复")


# ---------------------------------------------------------------------------
# 主校验
# ---------------------------------------------------------------------------

class TestCheckFidelity:
    def test_pass_when_all_numbers_in_source(self):
        result = check_fidelity(
            requirement="[条款] 保密期限不得短于 5 年",
            check_item="保密期限 ≥ 5 年",
            notes="",
            source_excerpt="保密期限自合同终止之日起 5 年。",
        )
        assert result.passed
        assert result.failures == ()

    def test_fail_when_number_invented(self):
        """实测华润案例：原文不含 60 天，模型却写出 60 天。"""
        result = check_fidelity(
            requirement="[条款] 付款期限不得超过 60 天",
            check_item="付款 ≤ 60 天",
            notes="",
            source_excerpt="付款条件按各大区实际填写。",
        )
        assert not result.passed
        assert any("60" in f for f in result.failures)

    def test_double_hallucination_should_be_discarded(self):
        """≥2 个失败 token → 标 discarded（在 orchestrator 阶段处理）。"""
        result = check_fidelity(
            requirement="[条款] 付款期限不得超过 60 天；优选 30 天",
            check_item="",
            notes="",
            source_excerpt="付款条件按各大区填写。",
        )
        assert not result.passed
        assert len(result.failures) >= 2

    def test_soft_voice_with_correct_number_passes_fidelity(self):
        """忠实度门只管数字 ground，不管语态。语态由 voice_check 管。"""
        result = check_fidelity(
            requirement="[条款] 保修金比例参考 3% 或 5%",
            check_item="",
            notes="",
            source_excerpt="保修金比例由发起人填写，一般为 3% 或 5%。",
        )
        assert result.passed

    def test_punctuation_tolerant(self):
        """容忍全/半角、空格、标点差异。"""
        result = check_fidelity(
            requirement="[条款] 总额不超过 30%",
            check_item="",
            notes="",
            source_excerpt="违约金总额不得超过合同总价的30%。",
        )
        assert result.passed


# ---------------------------------------------------------------------------
# 语态校验
# ---------------------------------------------------------------------------

class TestVoiceCheck:
    def test_detect_strong(self):
        assert detect_voice("不得低于 5 年") == "strong"

    def test_detect_soft(self):
        assert detect_voice("一般为 3% 或 5%") == "soft"

    def test_mixed_treated_as_soft(self):
        # 软优先：保守
        assert detect_voice("应当一般填写") == "soft"

    def test_soft_source_strong_req_fails(self):
        failures = check_voice_match(
            source_excerpt="保修金比例由发起人填写，一般为 3% 或 5%。",
            requirement="[条款] 保修金比例不得低于 3%",
        )
        assert failures
        assert failures[0] == "voice_strong_for_soft_source"

    def test_strong_source_strong_req_ok(self):
        failures = check_voice_match(
            source_excerpt="违约金不得超过合同总价的 30%。",
            requirement="[条款] 违约金不得超过 30%",
        )
        assert failures == []


# ---------------------------------------------------------------------------
# 占位识别
# ---------------------------------------------------------------------------

class TestPlaceholderDetect:
    def test_bracket(self):
        spans = detect_placeholders("付款比例【】%")
        assert spans
        assert spans[0].kind == "bracket"

    def test_xx_time(self):
        spans = detect_placeholders("应在 XX 天内回复")
        assert any(s.kind == "xx_time" for s in spans)

    def test_literal_placeholder(self):
        spans = detect_placeholders("付款条件按各大区填写")
        assert any(s.kind == "literal_placeholder" for s in spans)

    def test_no_placeholder_in_clean_text(self):
        assert detect_placeholders("保密期限 5 年") == []


class TestIsPlaceholderRule:
    def test_threshold_type_placeholder(self):
        assert is_placeholder_rule(
            requirement="[条款] 按经办人填写", notes="",
            threshold_type="占位", self_confidence=0.85,
        )

    def test_low_confidence(self):
        assert is_placeholder_rule(
            requirement="[条款] something", notes="",
            threshold_type="期限", self_confidence=0.30,
        )

    def test_notes_keyword(self):
        assert is_placeholder_rule(
            requirement="[条款] foo", notes="此规则为占位",
            threshold_type="期限", self_confidence=0.85,
        )

    def test_normal_rule_not_placeholder(self):
        assert not is_placeholder_rule(
            requirement="[条款] 保密期限不得短于 5 年", notes="",
            threshold_type="期限", self_confidence=0.9,
        )
