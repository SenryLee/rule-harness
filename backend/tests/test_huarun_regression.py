"""华润手册实测的 7 个幻觉案例回归测试。

每个用例都模拟"LLM 已经吐出了幻觉规则"的场景，验证 v1.1 第五重门（忠实度）
+ 语态校验 + 占位识别能将这些规则正确拦截。

参考：``规则抽取效果对比分析.md``
"""
from __future__ import annotations

import pytest

from backend.fidelity import check_fidelity
from backend.voice_check import check_voice_match
from backend.placeholder_detector import is_placeholder_rule


@pytest.mark.regression
class TestHuarunHallucinationCases:
    """
    每个 test_h* 对应分析报告中的 H1-H7 案例：
      H1 - 付款期限编 60 天
      H2 - 佣金比例编 5%
      H3 - 违约金 10/20% 过度泛化
      H4 - 违约金 5%/10% 数值幻觉
      H5 - 客户归属认定天数 3 天 / 方向反
      H6 - 保修金 3% 软语态升格
      H7 - 策略层注入（"阶梯沟通"）
    """

    def test_h1_payment_60_days_caught(self):
        """付款期限不得超过 60 天 — 60 / 30 都在原文里找不到"""
        result = check_fidelity(
            requirement="[条款] 付款期限不得超过 60 天；优选 30 天",
            check_item="",
            notes="",
            source_excerpt="付款条件按各大区实际填写。",
        )
        assert not result.passed
        # 至少有一个失败 token 是数字（60 或 30）
        assert any(("60" in f or "30" in f) for f in result.failures)

    def test_h2_commission_5pct_caught(self):
        result = check_fidelity(
            requirement="[条款] 佣金比例不得超过 5%；优选 3% 以内",
            check_item="",
            notes="",
            source_excerpt="按各大区实际填写。",
        )
        assert not result.passed

    def test_h3_overgeneralization_caught(self):
        """原文只针对咨询服务合同提到 20%，被泛化为通用规则。"""
        # 注意：通用规则的 source_excerpt 不应包含咨询服务的具体语境
        result = check_fidelity(
            requirement="[条款] 逾期交付违约金比例不得低于 10%，优选 20%",
            check_item="",
            notes="",
            source_excerpt="违约金金额为合同总价款的 20%。",  # 咨询服务的语境
        )
        # 10% 找不到 → 失败
        assert not result.passed
        assert any("10" in f for f in result.failures)

    def test_h4_breach_fee_5_10_pct_caught(self):
        result = check_fidelity(
            requirement="[条款] 违约金比例不得超过合同总价的 5%；若超过 10% 则不可接受",
            check_item="",
            notes="",
            source_excerpt="每次每项扣除合同总价的【】%……不得过高或过低。",
        )
        assert not result.passed
        # 5 和 10 都不在原文里
        assert any("5" in f for f in result.failures) or any("10" in f for f in result.failures)

    def test_h5_customer_attribution_3_days_caught(self):
        result = check_fidelity(
            requirement="[条款] 客户归属认定天数不得低于 3 天",
            check_item="客户归属认定 ≥ 3 天",
            notes="",
            source_excerpt="发起人填写客户归属认定的天数，统一为 7 天，此处 7 天仅为填写示例。",
        )
        assert not result.passed
        assert any("3" in f for f in result.failures)

    def test_h6_warranty_3pct_soft_voice_violation(self):
        """3% 在原文里有 — 忠实度通过；但语态违规——升格了软语态。"""
        fidelity = check_fidelity(
            requirement="[条款] 保修金比例不得低于 3%，优选 5%",
            check_item="",
            notes="",
            source_excerpt="保修金比例由发起人填写，一般为 3% 或 5%。",
        )
        assert fidelity.passed  # 数字都在原文里
        # 但语态校验失败
        voice_failures = check_voice_match(
            source_excerpt="保修金比例由发起人填写，一般为 3% 或 5%。",
            requirement="[条款] 保修金比例不得低于 3%，优选 5%",
        )
        assert voice_failures
        assert voice_failures[0] == "voice_strong_for_soft_source"

    def test_h7_strategy_injection_into_non_redline_doc(self):
        """非红线文件不应出现 P4 阶梯输出。这一项靠 P4 隔离测试保证；
        这里仅断言 P4 的 applicable 会拒绝普通审核手册。
        """
        from backend.pipelines.p4_redline import P4RedlinePipeline
        from backend.parsers import ParsedDocument

        # 模拟一份普通审核手册（不是公司红线）
        doc = ParsedDocument(
            sha256="x", filename="审核指引.docx", source_tag="标准条款库",
            priority=4, contract_types=["建设工程"], industry_context=None,
            is_scanned=False, blocks=(), comments=(), revisions=(),
            is_redline_doc=False,        # 关键：未明确标为红线
            is_case_doc=False, is_passthrough=False,
        )
        # 不需要真实 router；只调用 applicable
        class _FakePipe(P4RedlinePipeline):
            def __init__(self):
                pass  # 跳过真实构造
        pipe = _FakePipe()
        # is_redline_doc=False → 不适用
        assert not pipe.applicable(doc)
