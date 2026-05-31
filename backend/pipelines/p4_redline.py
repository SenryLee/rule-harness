"""P4 · 谈判红线/退让阶梯抽取管道。

输入：``ParsedDocument.is_redline_doc == True`` 的文档；按 ``blocks`` 切分。
输出：每个谈判点 1 条主规则；三档信息装入 ``RuleCandidate.ladder``。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ..config import Config
from ..harness import THEME_KEYS, validate_atomic
from ..llm import LLMRouter
from ..parsers import ParsedDocument, RuleCandidate
from .errors import record_llm_failure
from ..prompt_loader import PromptSections, load_prompt, render_system_user

logger = logging.getLogger(__name__)

PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "P4_redline_ladder_extract.txt"
)


class P4RedlinePipeline:
    pipeline_id = "P4"

    def __init__(self, router: LLMRouter, cfg: Config):
        self.router = router
        self.cfg = cfg
        self._prompt: PromptSections = load_prompt(PROMPT_PATH)

    def applicable(self, doc: ParsedDocument) -> bool:
        """P4 仅在文档被明确标记为谈判红线/谈判底线时启用。

        v1.1 修订：之前的判定过宽（只看 ``is_redline_doc``），导致 P4 在普通审核
        手册上也会触发，把"红线/阶梯沟通"语言无差别注入到所有规则的 ``notes``
        中——华润手册实测中 89% 规则受此污染。严格化为 AND 三条件：
          1. ``source_tag`` 在显式红线集合内
          2. ``is_redline_doc`` 标志位为 True
          3. 不是直通转换 / 案例文件
        """
        return (
            doc.source_tag in ("公司红线", "谈判底线")
            and doc.is_redline_doc
            and not doc.is_passthrough
            and not doc.is_case_doc
        )

    async def extract(self, doc: ParsedDocument, ctx: dict) -> list[RuleCandidate]:
        sem = asyncio.Semaphore(self.cfg.concurrency.blocks)

        async def one(block) -> list[RuleCandidate]:
            async with sem:
                return await self._extract_block(doc, block, ctx)

        bundles = await asyncio.gather(*[one(b) for b in doc.blocks])
        return [r for bundle in bundles for r in bundle]

    async def _extract_block(
        self, doc: ParsedDocument, block, ctx: dict
    ) -> list[RuleCandidate]:
        if not block.text or len(block.text.strip()) < 10:
            return []
        system_prompt, user_prompt = self._render_prompt(doc, block, ctx)
        try:
            obj = await self.router.chat_json(
                system=system_prompt, user=user_prompt, temperature=0.2
            )
        except Exception as exc:
            logger.exception("P4 LLM call failed for block %s in %s",
                             block.block_id, doc.filename)
            record_llm_failure(ctx, self.pipeline_id, doc.filename, block.block_id, exc)
            return []

        out: list[RuleCandidate] = []
        # 谈判红线优先级强制提升为 P2（公司红线）
        promoted_priority = min(doc.priority, 2)

        for rule in obj.get("rules", []) or []:
            kws = rule.get("keywords", [])
            if isinstance(kws, str):
                kws = [k.strip() for k in kws.split(",") if k.strip()]
            failures = validate_atomic(rule)

            ladder = {
                "preferred": str(rule.get("ladder_preferred", "")),
                "acceptable": str(rule.get("ladder_acceptable", "")),
                "unacceptable": str(rule.get("ladder_unacceptable", "")),
            }

            out.append(RuleCandidate(
                risk_level=str(rule.get("risk_level", "高")),
                keywords=tuple(kws),
                check_item=str(rule.get("check_item", "")),
                requirement=str(rule.get("requirement", "")),
                notes=str(rule.get("notes", "")),
                rule_type=str(rule.get("rule_type", "clause")),
                theme_key=str(rule.get("theme_key", "")),
                subject=str(rule.get("subject", "")),
                predicate=str(rule.get("predicate", "")),
                threshold_type=str(rule.get("threshold_type", "无")),
                direction=str(rule.get("direction", "反向")),
                source_excerpt=block.text,
                source_location=block.location,
                pipeline=self.pipeline_id,
                self_confidence=float(rule.get("self_confidence", 0.5)),
                uncertainty_points=tuple(rule.get("uncertainty_points", []) or ()),
                source_filename=doc.filename,
                source_sha256=doc.sha256,
                source_tag=doc.source_tag,
                priority=promoted_priority,
                contract_types=tuple(doc.contract_types),
                model=self.router.primary.name if self.router.primary else "",
                struct_check_pass=(len(failures) == 0),
                struct_failures=tuple(failures),
                ladder=ladder,
                output_target="negotiation",  # v1.1: P4 阶梯规则不进主 CSV
            ))
        return out

    def _render_prompt(
        self, doc: ParsedDocument, block, ctx: dict
    ) -> tuple[str, str]:
        redline_text = ", ".join(self.cfg.extraction.redline_keywords) or "无"
        theme_keys_text = "\n".join(sorted(THEME_KEYS))
        industry_text = (
            ctx.get("industry_context")
            or self.cfg.extraction.industry_vocabulary
            or "无"
        )
        contract_types_str = ", ".join(doc.contract_types) if doc.contract_types else "通用"
        return render_system_user(
            self._prompt,
            system_vars={
                "redline_keywords": redline_text,
                "theme_keys": theme_keys_text,
                "industry_context": industry_text,
            },
            user_vars={
                "filename": doc.filename,
                "source_tag": doc.source_tag,
                "priority": str(doc.priority),
                "contract_types": contract_types_str,
                "location": block.location,
                "block_text": block.text,
            },
        )
