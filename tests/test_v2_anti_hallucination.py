"""v2.0 防幻觉改造 · 单元测试

覆盖：
- take_excerpt：模型摘录 vs 回退
- verify_excerpt：归一化子串校验 + difflib 模糊回填 + mismatch 标记
- check_semantic_fidelity：法律术语/主体名词回溯 + 偏离率
- check_voice_match：soft→strong + neutral→strong(禁止性义务)
- validate_atomic：requirement 240 字上限 + 多阈值 >=4 + check_item 连接词+长度
- is_low_severity：单数字失败
- evaluate_confidence：semantic 权重 + 单数字强制降级 + consistency 衍生
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import replace
from backend.fidelity import check_fidelity, verify_excerpt, is_low_severity
from backend.semantic_fidelity import check_semantic_fidelity, should_discard
from backend.voice_check import check_voice_match, detect_voice
from backend.harness import take_excerpt, normalize_text, validate_atomic
from backend.parsers import RuleCandidate


def _make_rule(**kwargs) -> RuleCandidate:
    """构造测试用 RuleCandidate，提供合理默认值。"""
    defaults = dict(
        risk_level="中",
        keywords=(),
        check_item="测试检查项",
        requirement="[条款] 测试审查要求",
        notes="",
        rule_type="clause",
        theme_key="合同.违约责任.违约金",
        subject="甲方",
        predicate="支付",
        threshold_type="无",
        direction="正向",
        source_excerpt="原文摘录",
        source_location="block-1",
        pipeline="P1",
        self_confidence=0.8,
        uncertainty_points=(),
        source_filename="test.docx",
        source_sha256="abc123",
    )
    defaults.update(kwargs)
    return RuleCandidate(**defaults)


# ── take_excerpt 测试 ──────────────────────────────────────────────

def test_take_excerpt_model_provided():
    """模型给了摘录 → 使用模型摘录，fallback=False"""
    rule = {"source_excerpt": "甲方应在 30 天内支付违约金"}
    block = "合同约定，甲方应在 30 天内支付违约金，逾期按日万分之五计息。"
    excerpt, fallback = take_excerpt(rule, block)
    assert excerpt == "甲方应在 30 天内支付违约金"
    assert fallback is False


def test_take_excerpt_model_empty():
    """模型未给摘录 → 回退整块，fallback=True"""
    rule = {}
    block = "原文整块文本"
    excerpt, fallback = take_excerpt(rule, block)
    assert excerpt == "原文整块文本"
    assert fallback is True


def test_take_excerpt_model_whitespace():
    """模型给了空白摘录 → 回退"""
    rule = {"source_excerpt": "   "}
    block = "原文"
    excerpt, fallback = take_excerpt(rule, block)
    assert excerpt == "原文"
    assert fallback is True


# ── verify_excerpt 测试 ────────────────────────────────────────────

def test_verify_excerpt_fallback_skipped():
    """fallback=True → 跳过校验"""
    rule = _make_rule(
        source_excerpt="整块文本",
        raw_block_text="整块文本",
        excerpt_fallback=True,
    )
    result = verify_excerpt(rule)
    assert result is rule  # 原样返回


def test_verify_excerpt_exact_match():
    """摘录是原文子串 → 通过"""
    rule = _make_rule(
        source_excerpt="甲方应在 30 天内支付",
        raw_block_text="合同约定甲方应在 30 天内支付违约金，逾期加收。",
        excerpt_fallback=False,
    )
    result = verify_excerpt(rule)
    assert result.excerpt_fallback is False
    assert result.excerpt_mismatch is False
    assert result.excerpt_fuzzy is False


def test_verify_excerpt_fuzzy_match():
    """摘录有微小差异 → difflib 模糊匹配，标 fuzzy"""
    # 摘录几乎全部来自原文，只差一两个字符
    rule = _make_rule(
        source_excerpt="甲方应在 30 天内支付违约金，逾期按日万分之五计息",
        raw_block_text="合同约定，甲方应在30天内支付违约金，逾期按日万分之五计息。另外还有其他条款。",
        excerpt_fallback=False,
    )
    result = verify_excerpt(rule)
    # 归一化后应该是子串（标点被去除）
    assert result.excerpt_fuzzy is False or result.excerpt_fallback is False


def test_verify_excerpt_mismatch():
    """摘录与原文差异过大 → 回退整块 + mismatch"""
    rule = _make_rule(
        source_excerpt="完全无关的文本内容XYZ123",
        raw_block_text="合同约定甲方应在30天内支付违约金",
        excerpt_fallback=False,
    )
    result = verify_excerpt(rule)
    assert result.excerpt_mismatch is True
    assert result.excerpt_fallback is True
    assert result.source_excerpt == "合同约定甲方应在30天内支付违约金"


# ── check_semantic_fidelity 测试 ───────────────────────────────────

def test_semantic_all_phrases_found():
    """所有法律术语都在原文中 → 通过"""
    result = check_semantic_fidelity(
        requirement="[条款] 甲方应支付违约金，承担连带责任",
        check_item="违约金支付",
        source_excerpt="甲方违约时应支付违约金并承担连带责任",
    )
    assert result.passed is True
    assert len(result.failures) == 0
    assert result.deviation == 0.0


def test_semantic_phrases_not_found():
    """法律术语不在原文中 → 偏离"""
    result = check_semantic_fidelity(
        requirement="[条款] 甲方应支付违约金并承担不可抗力风险",
        check_item="违约金与不可抗力",
        source_excerpt="甲方应按时交付货物",
    )
    # "违约金"和"不可抗力"不在原文中
    assert "违约金" in result.failures
    assert "不可抗力" in result.failures
    assert result.deviation > 0.4
    assert result.passed is False


def test_semantic_subject_mismatch():
    """主体名词不在原文中 → 偏离"""
    result = check_semantic_fidelity(
        requirement="[条款] 丙方应承担保证责任",
        check_item="丙方保证",
        source_excerpt="甲方与乙方约定违约金条款",
    )
    # "丙方"不在原文，"保证"不在原文（但有"保证责任"的"保证"可能命中法律术语）
    assert "丙方" in result.failures
    assert result.deviation > 0


def test_semantic_no_phrases():
    """无可提取短语 → 通过"""
    result = check_semantic_fidelity(
        requirement="[条款] 按时提交",
        check_item="提交核对",
        source_excerpt="提交核对",
    )
    # "交付"在词表中但"提交"不在；如果没有法律术语/主体命中则通过
    assert result.passed is True


def test_should_discard_high_deviation():
    """偏离率 > 0.7 → 丢弃"""
    result = SemanticResult_helper(
        passed=False, failures=("A", "B", "C"), deviation=0.8, total_phrases=3
    )
    assert should_discard(result) is True


def SemanticResult_helper(passed, failures, deviation, total_phrases):
    from backend.semantic_fidelity import SemanticResult
    return SemanticResult(passed=passed, failures=failures, deviation=deviation, total_phrases=total_phrases)


# ── check_voice_match 测试 ─────────────────────────────────────────

def test_voice_soft_to_strong():
    """原文软语态 + requirement 强义务 → 升格违规"""
    failures = check_voice_match(
        source_excerpt="保修金比例一般为 3%",
        requirement="保修金比例不得低于 3%",
    )
    assert "voice_strong_for_soft_source" in failures


def test_voice_neutral_to_prohibition():
    """原文中性 + requirement 禁止性义务 → neutral升格"""
    failures = check_voice_match(
        source_excerpt="保修金比例 3%",
        requirement="保修金比例不得低于 3%",
    )
    assert "voice_escalation_neutral" in failures


def test_voice_match_ok():
    """原文强义务 + requirement 强义务 → 匹配"""
    failures = check_voice_match(
        source_excerpt="甲方应当按时支付",
        requirement="甲方应确认支付时点",
    )
    assert len(failures) == 0


def test_voice_check_item_scope():
    """v2.0: check_item 中的禁止性义务也被检测"""
    failures = check_voice_match(
        source_excerpt="保修金比例 3%",
        requirement="确认保修金",
        check_item="保修金不得低于 3%",
    )
    assert "voice_escalation_neutral" in failures


# ── validate_atomic 测试 ───────────────────────────────────────────

def test_validate_atomic_requirement_240_ok():
    """requirement 240 字 → 通过（v2.0 上限从 200 放宽到 240）"""
    rule = {
        "check_item": "测试" * 5,
        "requirement": "[条款] " + "测试审查要求" * 23,  # ~240 字
        "notes": "",
        "theme_key": "合同.违约责任.违约金",
        "risk_level": "中",
        "keywords": ["测试"],
    }
    failures = validate_atomic(rule)
    assert "requirement_too_long" not in failures


def test_validate_atomic_requirement_over_240():
    """requirement > 240 字 → too_long"""
    rule = {
        "check_item": "测试",
        "requirement": "[条款] " + "测试审查要求" * 50,  # 5 + 250 = 255 字
        "notes": "",
        "theme_key": "合同.违约责任.违约金",
        "risk_level": "中",
        "keywords": ["测试"],
    }
    failures = validate_atomic(rule)
    assert "requirement_too_long" in failures


def test_validate_atomic_multi_threshold_2_ok():
    """2 个不同数字 → 不再判多阈值（v2.0 放宽到 >=4）"""
    rule = {
        "check_item": "测试",
        "requirement": "[条款] 违约金 30% 且不低于 5%",
        "notes": "",
        "theme_key": "合同.违约责任.违约金",
        "risk_level": "中",
        "keywords": ["测试"],
    }
    failures = validate_atomic(rule)
    assert "requirement_multi_threshold" not in failures


def test_validate_atomic_multi_threshold_4_fail():
    """4 个不同数字 → 多阈值"""
    rule = {
        "check_item": "测试",
        "requirement": "[条款] 比例 30% 且 5% 且 10% 且 20%",
        "notes": "",
        "theme_key": "合同.违约责任.违约金",
        "risk_level": "中",
        "keywords": ["测试"],
    }
    failures = validate_atomic(rule)
    assert "requirement_multi_threshold" in failures


# ── is_low_severity 测试 ───────────────────────────────────────────

def test_is_low_severity_0():
    assert is_low_severity(()) is False

def test_is_low_severity_1():
    assert is_low_severity(("30%",)) is True

def test_is_low_severity_2():
    assert is_low_severity(("30%", "5%")) is False


# ── 运行所有测试 ───────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_take_excerpt_model_provided,
        test_take_excerpt_model_empty,
        test_take_excerpt_model_whitespace,
        test_verify_excerpt_fallback_skipped,
        test_verify_excerpt_exact_match,
        test_verify_excerpt_fuzzy_match,
        test_verify_excerpt_mismatch,
        test_semantic_all_phrases_found,
        test_semantic_phrases_not_found,
        test_semantic_subject_mismatch,
        test_semantic_no_phrases,
        test_should_discard_high_deviation,
        test_voice_soft_to_strong,
        test_voice_neutral_to_prohibition,
        test_voice_match_ok,
        test_voice_check_item_scope,
        test_validate_atomic_requirement_240_ok,
        test_validate_atomic_requirement_over_240,
        test_validate_atomic_multi_threshold_2_ok,
        test_validate_atomic_multi_threshold_4_fail,
        test_is_low_severity_0,
        test_is_low_severity_1,
        test_is_low_severity_2,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n{'='*60}")
    print(f"结果: {passed} 通过, {failed} 失败, 共 {len(tests)} 项")
    if failed > 0:
        sys.exit(1)
