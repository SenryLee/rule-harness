"""P2 · Word 批注规则抽取管道。

输入：``ParsedDocument.comments``（每条 ``CommentBlock``）
输出：每条批注转化为 1+ 条原子规则；优先级在调用方提升为"公司红线/内部制度"层级。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ..config import Config
from ..harness import THEME_KEYS, validate_atomic
from ..llm import LLMRouter
from ..parsers import CommentBlock, ParsedDocument, RuleCandidate
from ..prompt_loader import PromptSections, load_prompt, render_system_user

logger = logging.getLogger(__name__)

PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "P2_comment_extract.txt"
)


class P2CommentPipeline:
    pipeline_id = "P2"

    def __init__(self, router: LLMRouter, cfg: Config):
        self.router = router
        self.cfg = cfg
        self._prompt: PromptSections = load_prompt(PROMPT_PATH)

    def applicable(self, doc: ParsedDocument) -> bool:
        return bool(doc.comments) and not doc.is_passthrough and not doc.is_case_doc

    async def extract(self, doc: ParsedDocument, ctx: dict) -> list[RuleCandidate]:
        sem = asyncio.Semaphore(self.cfg.concurrency.blocks)

        async def one(comment: CommentBlock) -> list[RuleCandidate]:
            async with sem:
                return await self._extract_comment(doc, comment, ctx)

        bundles = await asyncio.gather(*[one(c) for c in doc.comments])
        return [r for bundle in bundles for r in bundle]

    async def _extract_comment(
        self, doc: ParsedDocument, comment: CommentBlock, ctx: dict
    ) -> list[RuleCandidate]:
        system_prompt, user_prompt = self._render_prompt(doc, comment, ctx)
        try:
            obj = await self.router.chat_json(
                system=system_prompt, user=user_prompt, temperature=0.2
            )
        except Exception:
            logger.exception("P2 LLM call failed for comment %s in %s",
                             comment.comment_id, doc.filename)
            return []

        out: list[RuleCandidate] = []
        for rule in obj.get("rules", []):
            kws = rule.get("keywords", [])
            if isinstance(kws, str):
                kws = [k.strip() for k in kws.split(",") if k.strip()]
            uncertainty = rule.get("uncertainty_points", [])
            if isinstance(uncertainty, str):
                uncertainty = [u.strip() for u in uncertainty.split(";") if u.strip()]

            failures = validate_atomic(rule)
            # 批注优先级提升：默认为"公司红线/内部制度"层（priority 2-3），取较高者
            promoted_priority = min(doc.priority, 2)

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
                direction=str(rule.get("direction", "正向")),
                source_excerpt=comment.text,
                source_location=f"comment-{comment.comment_id}@{comment.anchor_location}",
                pipeline=self.pipeline_id,
                self_confidence=float(rule.get("self_confidence", 0.5)),
                uncertainty_points=tuple(uncertainty),
                source_filename=doc.filename,
                source_sha256=doc.sha256,
                source_tag=doc.source_tag,
                priority=promoted_priority,
                contract_types=tuple(doc.contract_types),
                model=self.router.primary.name if self.router.primary else "",
                struct_check_pass=(len(failures) == 0),
                struct_failures=tuple(failures),
            ))
        return out

    def _render_prompt(
        self, doc: ParsedDocument, comment: CommentBlock, ctx: dict
    ) -> tuple[str, str]:
        redline_text = ", ".join(self.cfg.extraction.redline_keywords) or "无"
        theme_keys_text = "\n".join(sorted(THEME_KEYS))
        return render_system_user(
            self._prompt,
            system_vars={
                "redline_keywords": redline_text,
                "theme_keys": theme_keys_text,
            },
            user_vars={
                "filename": doc.filename,
                "author": comment.author or "未知",
                "anchor_paragraph": comment.anchor_text or comment.anchor_location or "未知",
                "comment_text": comment.text,
            },
        )
