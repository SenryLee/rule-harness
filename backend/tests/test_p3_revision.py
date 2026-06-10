from __future__ import annotations

import asyncio
from types import SimpleNamespace

from backend.parsers import ParsedDocument, RevisionBlock
from backend.pipelines.p3_revision import P3RevisionPipeline


def _doc() -> ParsedDocument:
    rev = RevisionBlock(
        rev_id="r1",
        original_text="预存￥200,000.00元返点20%消费款",
        revised_text="预存￥200,000.00元赠送20%消费款",
        location="paragraph-26",
    )
    return ParsedDocument(
        sha256="abc",
        filename="合同.docx",
        source_tag="历史合同",
        priority=5,
        contract_types=["酒店预付款"],
        industry_context=None,
        is_scanned=False,
        blocks=(),
        comments=(),
        revisions=(rev,),
        is_redline_doc=False,
        is_case_doc=False,
        is_passthrough=False,
    )


class _FakeRouter:
    """返回固定 fallback_clauses 的假 router，模拟"返点→赠送"修订。"""

    primary = SimpleNamespace(name="fake-model")

    async def chat_json(self, *, system, user, temperature=0.1):
        return {
            "interpretation": "返点改为赠送",
            "fallback_clauses": [
                {
                    "theme_key": "discount.rebate.adjustment",
                    "original_position": "返点",
                    "fallback_position": "赠送",
                    "subject": "甲方",
                    "self_confidence": 0.8,
                }
            ],
            "new_rules": [],
        }


def test_p3_fallback_rule_is_complete_and_chinese():
    cfg = SimpleNamespace(concurrency=SimpleNamespace(blocks=2))
    pipe = P3RevisionPipeline(_FakeRouter(), cfg)
    rules = asyncio.run(pipe.extract(_doc(), ctx={}))

    assert len(rules) == 1
    r = rules[0]
    # 三要素齐全，不再是半成品空字段
    assert r.assumption.strip()
    assert r.behavior_mode.strip()
    assert r.consequence.strip()
    # 不再泄漏英文 theme_key 叶子（曾出现 "可接受替代方案：adjustment"）
    assert "adjustment" not in r.check_item
    # 检查项体现具体修订内容
    assert "返点" in r.check_item and "赠送" in r.check_item
    # 替代口径仍记录在 notes 供 dedupe/审查使用
    assert "[FALLBACK]" in r.notes
    assert r.check_item == r.check_item[:40]  # 长度约束
