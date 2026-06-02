from __future__ import annotations

import asyncio
import csv

from backend.config import load_config
from backend.exporter import export_main_csv, export_metadata_csv
from backend.parsers import ContentBlock, ParsedDocument, RuleCandidate
from backend.pipelines.p1_body import P1BodyPipeline


class _Primary:
    name = "test-model"


class _Router:
    primary = _Primary()

    async def chat_json(self, **kwargs):
        return {
            "informational": False,
            "rules": [
                {
                    "risk_level": "中",
                    "keywords": ["付款", "验收", "节点"],
                    "check_item": "付款是否挂钩验收",
                    "requirement": "[条款] 付款条件应与验收节点挂钩",
                    "notes": "核对付款节点和验收节点是否一致。",
                    "rule_type": "clause",
                    "theme_key": "payment.term.days",
                    "subject": "买方",
                    "predicate": "应约定",
                    "threshold_type": "无",
                    "direction": "正向",
                    "self_confidence": 0.86,
                    "uncertainty_points": [],
                    "assumption": "采购合同设置分期付款时适用。",
                    "behavior_mode": "要求付款安排匹配验收节点。",
                    "consequence": "付款脱离验收可能造成履约风险。",
                    "exception_conditions": "",
                    "review_action": "核对付款节点、验收节点和付款条件。",
                }
            ],
        }


def _doc() -> ParsedDocument:
    return ParsedDocument(
        sha256="sha",
        filename="采购模板.docx",
        source_tag="合同模板",
        priority=5,
        contract_types=["采购"],
        industry_context=None,
        is_scanned=False,
        blocks=(ContentBlock("b1", "付款条件应与验收节点挂钩。", "p1", "paragraph"),),
        comments=(),
        revisions=(),
        is_redline_doc=False,
        is_case_doc=False,
        is_passthrough=False,
    )


def _rule(**overrides) -> RuleCandidate:
    defaults = {
        "risk_level": "中",
        "keywords": ("付款", "验收"),
        "check_item": "付款条件是否明确",
        "requirement": "[条款] 付款条件应与验收节点挂钩",
        "notes": "用于采购模板付款条款。",
        "rule_type": "clause",
        "theme_key": "payment.term.days",
        "subject": "买方",
        "predicate": "应约定",
        "threshold_type": "无",
        "direction": "正向",
        "source_excerpt": "付款条件应与验收节点挂钩。",
        "source_location": "p1",
        "pipeline": "P1",
        "self_confidence": 0.8,
        "uncertainty_points": (),
        "source_filename": "手册.docx",
        "source_sha256": "sha",
        "source_tag": "标准条款库",
        "priority": 4,
        "contract_types": ("采购",),
        "model": "test",
    }
    defaults.update(overrides)
    return RuleCandidate(**defaults)


def test_main_csv_stays_strictly_seven_columns(tmp_path):
    output = tmp_path / "main.csv"
    export_main_csv([_rule(assumption="审计字段不进入主表")], output)

    with output.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))

    assert len(rows[0]) == 7
    assert len(rows[1]) == 7
    assert rows[0] == [
        "规则项id",
        "是否启用",
        "风险程度",
        "关键词",
        "检查项",
        "审查要求",
        "审查说明",
    ]


def test_metadata_csv_includes_rule_analysis_columns(tmp_path):
    output = tmp_path / "metadata.csv"
    export_metadata_csv([
        _rule(
            assumption="采购合同设置分期付款时适用。",
            behavior_mode="要求付款安排匹配验收节点。",
            consequence="付款脱离验收可能造成履约风险。",
            exception_conditions="预付款安排另行约定。",
            review_action="核对付款节点、验收节点和付款条件。",
            transformation_note="将付款安排转化为付款节点审查规则。",
        )
    ], output)

    with output.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    assert rows[0]["前提假设"] == "采购合同设置分期付款时适用。"
    assert rows[0]["行为模式"] == "要求付款安排匹配验收节点。"
    assert rows[0]["后果"] == "付款脱离验收可能造成履约风险。"
    assert rows[0]["例外条件"] == "预付款安排另行约定。"
    assert rows[0]["审查动作"] == "核对付款节点、验收节点和付款条件。"
    assert rows[0]["转化说明"] == "将付款安排转化为付款节点审查规则。"


def test_p1_pipeline_reads_analysis_fields_with_empty_defaults():
    pipe = P1BodyPipeline(_Router(), load_config())

    rules = asyncio.run(pipe.extract(_doc(), {}))

    assert len(rules) == 1
    assert rules[0].assumption == "采购合同设置分期付款时适用。"
    assert rules[0].behavior_mode == "要求付款安排匹配验收节点。"
    assert rules[0].consequence == "付款脱离验收可能造成履约风险。"
    assert rules[0].exception_conditions == ""
    assert rules[0].review_action == "核对付款节点、验收节点和付款条件。"
    assert rules[0].transformation_note == ""


def test_api_serializes_rule_analysis_fields_and_defaults():
    from backend.orchestrator import candidate_to_api_dict

    detailed = candidate_to_api_dict(_rule(review_action="核对付款条件。"))
    compatible = candidate_to_api_dict(_rule())

    assert detailed["review_action"] == "核对付款条件。"
    assert compatible["assumption"] == ""
    assert compatible["behavior_mode"] == ""
    assert compatible["consequence"] == ""
    assert compatible["exception_conditions"] == ""
    assert compatible["review_action"] == ""
    assert compatible["transformation_note"] == ""
