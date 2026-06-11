"""v1.4 新功能测试：自动命名 / 四段式增强门 / 跨任务合并 / 导出注册表 / 细化参数。"""
from __future__ import annotations

from dataclasses import replace as dc_replace

from backend.config import load_config
from backend.export_dicts import (
    FIELD_REGISTRY,
    LOCATED_COLUMNS,
    TEMPLATE_COLUMNS,
    field_catalog,
    rules_to_csv,
)
from backend.folder_merge import merge_rules_across_batches
from backend.orchestrator import _apply_task_overrides, _enrich_short_requirements
from backend.parsers import RuleCandidate
from backend.routes.batch_routes import auto_batch_name


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


# ── 自动命名 ──

def test_auto_batch_name_single_and_multi():
    single = auto_batch_name([{"original_name": "房产赠与合同纠纷案例.docx"}])
    assert single.startswith("房产赠与合同纠纷案例 · ")
    multi = auto_batch_name([
        {"original_name": "民法典合同编.pdf"},
        {"original_name": "公司法.pdf"},
        {"original_name": "审查手册.docx"},
    ])
    assert "民法典合同编 等3件 · " in multi


def test_auto_batch_name_truncates_long_stem():
    name = auto_batch_name([{"original_name": "这是一个超级无敌长到根本放不下的法律文件名称示例.docx"}])
    assert "…" in name


# ── 四段式本地增强门 ──

def test_enrich_short_requirement_assembles_four_parts():
    rule = _mk(
        requirement="[条款] 保密期限不得短于3年",
        behavior_mode="受信方应当承担不少于3年的保密义务",
        exception_conditions="",
        review_action="核对保密条款期限起算点",
    )
    out = _enrich_short_requirements([rule])[0]
    assert "核验：" in out.requirement
    assert "例外：原文未见明确例外" in out.requirement
    assert "不满足处理：核对保密条款期限起算点" in out.requirement


def test_enrich_skips_long_placeholder_and_direct():
    long_req = "[条款] " + "审查要求内容" * 20
    long_rule = _mk(requirement=long_req)
    placeholder = _mk(threshold_type="占位", requirement="[条款] 本项按经办人据实填写")
    direct = _mk(pipeline="direct", requirement="[条款] 用户已有规则")
    outs = _enrich_short_requirements([long_rule, placeholder, direct])
    assert outs[0].requirement == long_req
    assert outs[1].requirement == placeholder.requirement
    assert outs[2].requirement == direct.requirement


# ── 跨任务合并去重 ──

def _api(rule_id: str, fp: str, **kw) -> dict:
    base = {
        "rule_id": rule_id,
        "fingerprint": fp,
        "theme_key": "confidentiality.term.duration",
        "subject": "受信方",
        "predicate": "不得短于",
        "threshold_type": "期限",
        "direction": "反向",
        "priority": 5,
        "combined_confidence": 0.8,
        "risk_level": "高",
        "requirement": "[条款] 保密期限不得短于3年",
        "output_target": "main",
    }
    base.update(kw)
    return base


def test_merge_dedupes_by_fingerprint_and_struct():
    merged, stats = merge_rules_across_batches({
        "b1": [_api("r1", "fp-same"), _api("r2", "fp-x", theme_key="payment.term.days", predicate="应当支付")],
        "b2": [
            _api("r3", "fp-same", priority=1),          # 指纹撞 r1，priority 更优胜出
            _api("r4", "fp-y", combined_confidence=0.9),  # 结构撞 r1（同五元组），并入 variants
        ],
    })
    assert stats["total_in"] == 4
    assert stats["fingerprint_dups_removed"] == 1
    assert stats["struct_dups_removed"] == 1
    assert stats["total_out"] == 2
    winner = next(r for r in merged if r["theme_key"] == "confidentiality.term.duration")
    assert winner["priority"] == 1  # 法规优先级的 r3 胜出
    assert winner.get("merge_variants")


def test_merge_filters_non_main_by_default():
    merged, stats = merge_rules_across_batches({
        "b1": [_api("r1", "f1"), _api("r2", "f2", output_target="discarded",
                                      theme_key="payment.term.days")],
    })
    assert stats["total_in"] == 1
    assert len(merged) == 1


# ── 导出注册表 ──

def test_template_and_located_columns_exist_in_registry():
    for col in TEMPLATE_COLUMNS + LOCATED_COLUMNS:
        assert col in FIELD_REGISTRY


def test_rules_to_csv_headers_match_user_template():
    csv_text = rules_to_csv([], TEMPLATE_COLUMNS)
    assert csv_text.splitlines()[0] == "规则项id,是否启用,风险程度,关键词,检查项,审查要求,审查说明"


def test_rules_to_csv_renders_values():
    rule = _api("R001", "fp", keywords=["关键词1", "关键词2"], enabled=True)
    csv_text = rules_to_csv([rule], TEMPLATE_COLUMNS)
    assert "R001" in csv_text
    assert "关键词1, 关键词2" in csv_text
    assert "启用" in csv_text


def test_field_catalog_groups():
    groups = {item["group"] for item in field_catalog()}
    assert {"基础", "深度分析", "结构画像", "原文溯源", "质量与置信", "适用范围"} <= groups


# ── 细化参数接线 ──

def test_fine_grained_overrides():
    cfg = load_config()
    out = _apply_task_overrides(cfg, [{
        "extraction_overrides": {
            "chunk_chars": 999999,   # clamp 到 4000
            "density_min": 3.5,
            "skip_strictness": "strict",
            "dedupe_level": 5,
        },
    }])
    assert out.extraction.chunk_chars == 4000
    assert out.extraction.density_min == 3.5
    assert out.extraction.skip_strictness == "strict"
    assert out.extraction.dedupe_level == 5


def test_dedupe_level_override_changes_grouping():
    from backend.dedupe import dedupe_with_priority

    cfg = load_config()
    # 同 theme+subject 但 check_item 不同的两条
    a = _mk(check_item="保密期限是否不少于3年")
    b = _mk(check_item="保密期限起算点是否明确", requirement="[条款] 起算点应明确")
    # dedupe_level=1：按 theme|subject 激进合并 → 1 条
    cfg1 = dc_replace(cfg, extraction=dc_replace(cfg.extraction, dedupe_level=1))
    assert len(dedupe_with_priority([a, b], cfg1)) == 1
    # dedupe_level=4：含 check_item → 2 条
    cfg4 = dc_replace(cfg, extraction=dc_replace(cfg.extraction, dedupe_level=4))
    assert len(dedupe_with_priority([a, b], cfg4)) == 2
