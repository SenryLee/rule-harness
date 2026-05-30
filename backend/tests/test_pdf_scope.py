from __future__ import annotations

import csv

from backend.exporter import export_metadata_csv
from backend.orchestrator import _apply_task_scope, _build_task_scope
from backend.parsers import ContentBlock, ParsedDocument, RuleCandidate, parse_pdf


def _doc(filename: str, source_tag: str, text: str) -> ParsedDocument:
    return ParsedDocument(
        sha256="sha",
        filename=filename,
        source_tag=source_tag,
        priority=5,
        contract_types=["采购"],
        industry_context=None,
        is_scanned=False,
        blocks=(ContentBlock("b1", text, "p1", "paragraph"),),
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


def test_parse_pdf_uses_ocr_when_scanned_and_enabled(tmp_path, monkeypatch):
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"not a real pdf")

    def fake_ocr(filepath, engine, language):
        return (ContentBlock("ocr-1", "扫描合同付款条款", "p1-ocr-1", "paragraph"),), None

    monkeypatch.setattr("backend.parsers._ocr_pdf_pages", fake_ocr)

    parsed = parse_pdf(
        path,
        source_tag="合同模板",
        contract_types=["采购"],
        is_scanned=True,
        ocr_enabled=True,
    )

    assert parsed.is_scanned is True
    assert parsed.blocks[0].text == "扫描合同付款条款"
    assert parsed.parse_warnings == ()


def test_template_focused_scope_routes_unmatched_rules_out_of_scope():
    template = _doc("采购模板.docx", "合同模板", "付款 验收 交付 违约责任")
    scope = _build_task_scope(
        [{"task_mode": "template_focused", "our_party": "买方"}],
        [template],
    )

    matched = _rule()
    unmatched = _rule(
        keywords=("保密", "竞业限制"),
        check_item="保密期限是否明确",
        requirement="[条款] 保密期限应明确",
        notes="保密规则。",
    )

    scoped = _apply_task_scope([matched, unmatched], scope)

    assert scoped[0].scope_match == "in_scope"
    assert scoped[0].output_target == "main"
    assert scoped[1].scope_match == "out_of_scope"
    assert scoped[1].output_target == "out_of_scope"


def test_metadata_export_includes_scope_columns(tmp_path):
    output = tmp_path / "metadata.csv"
    export_metadata_csv([
        _rule(
            task_mode="template_strategy",
            scope_match="in_scope",
            scope_reason="命中模板相关词: 付款",
            template_anchor="付款",
        )
    ], output)

    with output.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    assert rows[0]["任务模式"] == "template_strategy"
    assert rows[0]["范围匹配"] == "in_scope"
    assert rows[0]["模板锚点"] == "付款"
