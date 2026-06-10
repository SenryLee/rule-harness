from __future__ import annotations

import asyncio
from types import SimpleNamespace

from backend.orchestrator import BatchProgress
from backend.parsers import ContentBlock, ParsedDocument
from backend.pipelines.p1_body import P1BodyPipeline


def _doc() -> ParsedDocument:
    blocks = tuple(
        ContentBlock(block_id=f"p{i}", text=f"第{i}段内容。", location=str(i),
                     block_type="paragraph")
        for i in range(5)
    )
    return ParsedDocument(
        sha256="x", filename="f.pdf", source_tag="法规", priority=1,
        contract_types=[], industry_context=None, is_scanned=False,
        blocks=blocks, comments=(), revisions=(), is_redline_doc=False,
        is_case_doc=False, is_passthrough=False,
    )


class _CountingRouter:
    primary = SimpleNamespace(name="fake")

    def __init__(self):
        self.calls = 0

    async def chat_json(self, *, system, user, temperature=0.2):
        self.calls += 1
        return {"informational": False, "rules": []}


def test_cancel_requested_skips_remaining_blocks():
    router = _CountingRouter()
    pipe = P1BodyPipeline.__new__(P1BodyPipeline)
    pipe.router = router
    pipe.cfg = SimpleNamespace(concurrency=SimpleNamespace(blocks=4))
    pipe._render_prompt = lambda doc, block, ctx: ("sys", block.text)

    progress = BatchProgress(total_files=1)
    progress.cancel_requested = True  # 开跑前就已请求停止
    ctx = {"progress": progress}

    rules = asyncio.run(pipe.extract(_doc(), ctx))
    assert rules == []
    assert router.calls == 0  # 所有块被跳过，未发起任何 LLM 调用
