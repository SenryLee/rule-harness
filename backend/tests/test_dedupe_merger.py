"""Dedupe & merger sanity tests.

These bypass the LLM entirely — they exercise the pure-CPU portions of the
harness so we can prove the priority covers / conflict-detection logic is
correct independent of any model behavior.
"""
from __future__ import annotations

from backend.config import load_config
from backend.dedupe import build_rule_ids, dedupe_with_priority
from backend.harness import compute_fingerprint
from backend.merger import _encode_rule_for_merge, build_diff, rules_equivalent
from backend.parsers import RuleCandidate


def _mk(**kwargs) -> RuleCandidate:
    defaults = dict(
        risk_level="高",
        keywords=("保密期限",),
        check_item="保密期限是否不少于3年",
        requirement="[条款] 保密期限不得短于3年",
        notes="",
        rule_type="clause",
        theme_key="confidentiality.term.duration",
        subject="受信方",
        predicate="不得短于",
        threshold_type="期限",
        direction="反向",
        source_excerpt="保密期限自合同终止之日起 3 年。",
        source_location="p1",
        pipeline="P1",
        self_confidence=0.9,
        uncertainty_points=(),
        source_filename="a.docx",
        source_sha256="x",
        source_tag="历史合同",
        priority=5,
        contract_types=("采购",),
        model="deepseek",
        struct_check_pass=True,
        struct_failures=(),
    )
    defaults.update(kwargs)
    return RuleCandidate(**defaults)


def test_dedupe_picks_higher_priority():
    high = _mk(source_tag="法规", priority=1, requirement="[条款] 保密期限不得短于5年")
    low = _mk(source_tag="历史合同", priority=5)
    cfg = load_config()
    out = dedupe_with_priority([low, high], cfg)
    assert len(out) == 1
    assert out[0].source_tag == "法规"
    assert out[0].variant_versions  # 低优先级被存为 variant


def test_dedupe_threshold_conflict_flagged():
    a = _mk(requirement="[条款] 保密期限不得短于3年", source_tag="历史合同", priority=5)
    b = _mk(requirement="[条款] 保密期限不得短于5年", source_tag="标准条款库", priority=4)
    cfg = load_config()
    out = dedupe_with_priority([a, b], cfg)
    assert len(out) == 1
    assert out[0].conflict_flag == "阈值冲突"


def test_dedupe_keeps_distinct_atomic_rules_same_fingerprint():
    """回归：5 元组指纹相同但审查口径不同的原子规则不得被折叠。

    单一主题法规（如赠与章）里第658条任意撤销 + 第663条三种撤销情形共享
    theme+subject+predicate+threshold+direction，旧逻辑在 level>=3 会压成一条。
    """
    common = dict(
        theme_key="termination.cause.material_breach",
        subject="赠与人",
        predicate="可以撤销",
        threshold_type="无",
        direction="正向",
    )
    rules = [
        _mk(check_item="赠与人可否任意撤销赠与", requirement="[条款] 权利转移前可撤销", **common),
        _mk(check_item="受赠人严重侵害可否撤销", requirement="[条款] 严重侵害近亲属可撤销", **common),
        _mk(check_item="受赠人不履行扶养可否撤销", requirement="[条款] 不履行扶养义务可撤销", **common),
        _mk(check_item="受赠人不履行约定义务可否撤销", requirement="[条款] 不履行约定义务可撤销", **common),
    ]
    cfg = load_config()  # 运行档位 level=4
    out = dedupe_with_priority(rules, cfg)
    assert len(out) == 4, "不同审查口径的撤销情形应各自成规则，而非折叠为一条"


def test_build_rule_ids_prefix():
    cfg = load_config()
    rule = _mk(contract_types=("采购",), rule_type="clause")
    out = build_rule_ids([rule])
    assert out[0].rule_id.startswith("PUR-C-")
    assert len(out[0].fingerprint) == 6


def test_rules_equivalent_ignores_unrelated_fields():
    base = _mk()
    other = _mk(notes="completely different notes also ok?")
    a = _encode_rule_for_merge(base)
    b = _encode_rule_for_merge(other)
    # notes is in the equivalence set, so they differ:
    assert not rules_equivalent(a, b)


def test_build_diff_only_emits_changed_fields():
    base = _encode_rule_for_merge(_mk(requirement="[条款] 保密期限不得短于3年"))
    new = _encode_rule_for_merge(_mk(requirement="[条款] 保密期限不得短于5年"))
    diff = build_diff(base, new)
    assert "requirement" in diff
    assert "risk_level" not in diff


def test_fingerprint_normalizes_whitespace_in_direction():
    # 修复 B27：方向带空格也应当指纹一致
    rule_clean = {"theme_key": "x", "subject": "a", "predicate": "b",
                  "threshold_type": "无", "direction": "反向"}
    rule_ws = {"theme_key": "x", "subject": "a", "predicate": "b",
               "threshold_type": "无", "direction": "反向 "}
    assert compute_fingerprint(rule_clean) == compute_fingerprint(rule_ws)
