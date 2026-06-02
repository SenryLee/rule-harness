from __future__ import annotations

import asyncio

from backend.config import load_config
from backend.orchestrator import BatchProgress, _build_summary, _run_pipelines
from backend.parsers import ContentBlock, ParsedDocument, RuleCandidate


class FakeRouter:
    pass


class FakePipeline:
    pipeline_id = ""

    def __init__(self, router, cfg):
        pass

    def applicable(self, doc: ParsedDocument) -> bool:
        return False

    async def extract(self, doc: ParsedDocument, ctx: dict) -> list[RuleCandidate]:
        return []


class FakeP1(FakePipeline):
    pipeline_id = "P1"

    def applicable(self, doc: ParsedDocument) -> bool:
        return not doc.is_passthrough and not doc.is_redline_doc and not doc.is_case_doc

    async def extract(self, doc: ParsedDocument, ctx: dict) -> list[RuleCandidate]:
        return [_rule(doc, "P1")]


class FakeP2(FakePipeline):
    pipeline_id = "P2"


class FakeP3(FakePipeline):
    pipeline_id = "P3"


class FakeP4(FakePipeline):
    pipeline_id = "P4"

    def applicable(self, doc: ParsedDocument) -> bool:
        return doc.is_redline_doc

    async def extract(self, doc: ParsedDocument, ctx: dict) -> list[RuleCandidate]:
        return [_rule(doc, "P4")]


class FakeP5(FakePipeline):
    pipeline_id = "P5"

    def applicable(self, doc: ParsedDocument) -> bool:
        return doc.is_case_doc

    async def extract(self, doc: ParsedDocument, ctx: dict) -> list[RuleCandidate]:
        return [_rule(doc, "P5")]


class FakeDirect(FakePipeline):
    pipeline_id = "direct"


FAKE_PIPELINES = [FakeP1, FakeP2, FakeP3, FakeP4, FakeP5, FakeDirect]


def test_special_docs_keep_p1_basic_coverage(monkeypatch):
    monkeypatch.setattr("backend.orchestrator.ALL_PIPELINES", FAKE_PIPELINES)
    redline = _doc("红线.docx", "公司红线", is_redline=True)
    case = _doc("案例.docx", "案例", is_case=True)
    progress = BatchProgress(total_blocks=len(redline.blocks) + len(case.blocks))

    rules = asyncio.run(_run_pipelines(
        [redline, case],
        FakeRouter(),
        load_config(),
        progress,
    ))

    emitted = {(rule.source_filename, rule.pipeline) for rule in rules}
    assert ("红线.docx", "P1") in emitted
    assert ("红线.docx", "P4") in emitted
    assert ("案例.docx", "P1") in emitted
    assert ("案例.docx", "P5") in emitted
    assert progress.pipeline_progress["P1"].files_total == 2
    assert progress.pipeline_progress["P4"].files_total == 1
    assert progress.pipeline_progress["P5"].files_total == 1


def test_summary_contains_extraction_completeness_metrics():
    doc = _doc("合同.docx", "历史合同", blocks=3)
    progress = _prepared_progress([doc])
    progress.mark_pipeline_done("P1", "合同.docx", rules_emitted=1)

    summary = _build_summary([_rule(doc, "P1")], [], progress)

    completeness = summary["extraction_completeness"]
    assert completeness["parsed_blocks"] == 3
    assert completeness["total_blocks"] == 3
    assert completeness["rules_per_file"] == {"合同.docx": 1}
    assert completeness["low_output_files"] == []
    assert completeness["pipeline_coverage"]["P1"] == {
        "label": "正文抽取",
        "status": "done",
        "files_total": 1,
        "files_done": 1,
        "blocks_total": 3,
        "blocks_done": 3,
        "rules_emitted": 1,
    }


def test_low_output_files_flags_long_zero_output_file():
    doc = _doc("长文档.docx", "历史合同", blocks=10)
    progress = _prepared_progress([doc])
    progress.mark_pipeline_done("P1", "长文档.docx", rules_emitted=0)

    summary = _build_summary([], [], progress)

    low_files = summary["extraction_completeness"]["low_output_files"]
    assert low_files == [{
        "filename": "长文档.docx",
        "blocks_total": 10,
        "rules": 0,
        "p1_rules": 0,
        "reasons": ["no_rules", "basic_body_no_rules"],
    }]


def test_low_output_files_does_not_flag_short_zero_output_file():
    doc = _doc("短文档.docx", "历史合同", blocks=3)
    progress = _prepared_progress([doc])
    progress.mark_pipeline_done("P1", "短文档.docx", rules_emitted=0)

    summary = _build_summary([], [], progress)

    assert summary["extraction_completeness"]["low_output_files"] == []


def _prepared_progress(docs: list[ParsedDocument]) -> BatchProgress:
    progress = BatchProgress(total_blocks=sum(len(doc.blocks) for doc in docs))
    instances = [pipe(FakeRouter(), load_config()) for pipe in FAKE_PIPELINES]
    progress.prepare_pipeline_progress(docs, instances)
    return progress


def _doc(
    filename: str,
    source_tag: str,
    *,
    is_redline: bool = False,
    is_case: bool = False,
    blocks: int = 2,
) -> ParsedDocument:
    return ParsedDocument(
        sha256=filename,
        filename=filename,
        source_tag=source_tag,
        priority=5,
        contract_types=["通用商事"],
        industry_context=None,
        is_scanned=False,
        blocks=tuple(
            ContentBlock(
                block_id=f"p{i}",
                text=f"第{i}段 付款、违约和解除条件应当按照合同约定执行。",
                location=str(i),
                block_type="paragraph",
            )
            for i in range(blocks)
        ),
        comments=(),
        revisions=(),
        is_redline_doc=is_redline,
        is_case_doc=is_case,
        is_passthrough=False,
    )


def _rule(doc: ParsedDocument, pipeline: str) -> RuleCandidate:
    return RuleCandidate(
        risk_level="中",
        keywords=("付款",),
        check_item=f"{pipeline} 检查项",
        requirement="[条款] 应按约履行付款义务",
        notes="",
        rule_type="clause",
        theme_key="payment.schedule.deadline",
        subject="合同当事人",
        predicate="应履行",
        threshold_type="无",
        direction="正向",
        source_excerpt=doc.blocks[0].text,
        source_location=doc.blocks[0].location,
        pipeline=pipeline,
        self_confidence=0.8,
        uncertainty_points=(),
        source_filename=doc.filename,
        source_sha256=doc.sha256,
        source_tag=doc.source_tag,
        priority=doc.priority,
        contract_types=tuple(doc.contract_types),
        combined_confidence=0.8,
    )
