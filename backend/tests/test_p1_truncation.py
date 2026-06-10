from __future__ import annotations

import asyncio
from types import SimpleNamespace

from backend.parsers import ContentBlock, ParsedDocument
from backend.pipelines import p1_body
from backend.pipelines.p1_body import P1BodyPipeline


def _doc(block_text: str) -> ParsedDocument:
    return ParsedDocument(
        sha256="x", filename="long.pdf", source_tag="法规", priority=1,
        contract_types=[], industry_context=None, is_scanned=False,
        blocks=(ContentBlock(block_id="p36-0+2", text=block_text,
                             location="p36", block_type="chunk"),),
        comments=(), revisions=(), is_redline_doc=False, is_case_doc=False,
        is_passthrough=False,
    )


class _TruncateRouter:
    """输入 user 超过阈值就报截断，否则回 1 条规则。模拟密集页超 max_tokens。"""

    primary = SimpleNamespace(name="fake")

    def __init__(self, threshold: int):
        self.threshold = threshold

    async def chat_json(self, *, system, user, temperature=0.2):
        if len(user) > self.threshold:
            raise p1_body.LLMTruncatedError("Output truncated")
        return {
            "informational": False,
            "rules": [{
                "assumption": "适用。", "behavior_mode": "应当。", "consequence": "风险。",
                "risk_level": "中", "keywords": ["x", "y", "z"],
                "check_item": "检查项", "requirement": "[条款] 要求",
                "notes": "", "rule_type": "clause", "theme_key": "misc",
                "subject": "甲", "predicate": "应当", "threshold_type": "无",
                "direction": "正向", "self_confidence": 0.8, "uncertainty_points": [],
            }],
        }


def _pipe(router) -> P1BodyPipeline:
    cfg = SimpleNamespace(concurrency=SimpleNamespace(blocks=4))
    pipe = P1BodyPipeline.__new__(P1BodyPipeline)
    pipe.router = router
    pipe.cfg = cfg
    # 绕过提示词渲染，让 user 串携带 block 文本长度，专测截断恢复/切分逻辑
    pipe._render_prompt = lambda doc, block, ctx: ("sys", block.text)
    return pipe


def _ctx():
    return {"progress": SimpleNamespace(errors=[])}


def test_recursive_split_recovers_rules_from_dense_block():
    # 2000 字块，阈值 600：2000→1000→500，500<600 成功 → 4 片各 1 条
    block_text = "甲" * 2000
    pipe = _pipe(_TruncateRouter(threshold=600))
    ctx = _ctx()
    rules = _run(pipe, block_text, ctx)
    assert len(rules) == 4
    assert ctx["progress"].errors == []  # 全部恢复，无终态失败


def test_terminal_failure_only_when_too_small_to_split():
    # 永远截断：递归到 _MIN_SPLIT_CHARS / 最大深度后记终态失败，不无限递归
    block_text = "甲" * 2000
    pipe = _pipe(_TruncateRouter(threshold=0))  # 任何输入都截断
    ctx = _ctx()
    rules = _run(pipe, block_text, ctx)
    assert rules == []
    assert ctx["progress"].errors  # 至少一条 llm_failed 记录
    assert all("too small to split" in e for e in ctx["progress"].errors)


def _run(pipe, block_text, ctx):
    doc = _doc(block_text)
    return asyncio.run(pipe._extract_block(doc, doc.blocks[0], ctx))
