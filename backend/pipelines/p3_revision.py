"""P3 · Word 修订（ins/del）diff 抽取管道。

输入：``ParsedDocument.revisions``
输出：
  - 主要产出是 ``RevisionFallback`` 对象（不是新规则），由 dedupe 后合并到对应主规则的元数据；
  - 极少数情况下，全新条款会作为 ``RuleCandidate`` 输出。

为简化数据流，本管道把"fallback 信息"打包成特殊 ``RuleCandidate``：``rule_type='clause'``、
``pipeline='P3'``、``notes`` 字段以 ``[FALLBACK]`` 前缀承载替代方案。后续 dedupe 时通过
fingerprint 匹配到对应主规则；若无匹配，作为低优先级独立规则保留。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ..config import Config
from ..harness import THEME_KEYS, validate_atomic
from ..llm import LLMRouter
from ..parsers import ParsedDocument, RevisionBlock, RuleCandidate
from .errors import record_llm_failure
from ..prompt_loader import PromptSections, load_prompt, render_system_user

logger = logging.getLogger(__name__)

PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "P3_revision_diff_extract.txt"
)


class P3RevisionPipeline:
    pipeline_id = "P3"

    def __init__(self, router: LLMRouter, cfg: Config):
        self.router = router
        self.cfg = cfg
        self._prompt: PromptSections = load_prompt(PROMPT_PATH)

    def applicable(self, doc: ParsedDocument) -> bool:
        return bool(doc.revisions) and not doc.is_passthrough and not doc.is_case_doc

    async def extract(self, doc: ParsedDocument, ctx: dict) -> list[RuleCandidate]:
        sem = asyncio.Semaphore(self.cfg.concurrency.blocks)

        async def one(rev: RevisionBlock) -> list[RuleCandidate]:
            async with sem:
                return await self._extract_revision(doc, rev, ctx)

        bundles = await asyncio.gather(*[one(r) for r in doc.revisions])
        return [r for bundle in bundles for r in bundle]

    async def _extract_revision(
        self, doc: ParsedDocument, rev: RevisionBlock, ctx: dict
    ) -> list[RuleCandidate]:
        system_prompt, user_prompt = self._render_prompt(doc, rev)
        try:
            obj = await self.router.chat_json(
                system=system_prompt, user=user_prompt, temperature=0.1
            )
        except Exception as exc:
            logger.exception("P3 LLM call failed for revision %s in %s",
                             rev.rev_id, doc.filename)
            record_llm_failure(ctx, self.pipeline_id, doc.filename, rev.rev_id, exc)
            return []

        out: list[RuleCandidate] = []

        # fallback_clauses 转 RuleCandidate with [FALLBACK] notes
        for fc in obj.get("fallback_clauses", []) or []:
            theme_key = str(fc.get("theme_key", ""))
            if not theme_key:
                continue
            note = (f"[FALLBACK] 原口径={fc.get('original_position','')}; "
                    f"可接受替代={fc.get('fallback_position','')}; "
                    f"主体={fc.get('subject','')}")
            out.append(RuleCandidate(
                risk_level="中",
                keywords=(theme_key.split(".")[-1],),
                check_item=f"可接受替代方案：{fc.get('theme_key','').split('.')[-1]}"[:30],
                requirement=f"[条款] 已存在替代口径：{fc.get('fallback_position','')}"[:200],
                notes=note,
                rule_type="clause",
                theme_key=theme_key,
                subject=str(fc.get("subject", "")),
                predicate="可接受替代",
                threshold_type="无",
                direction="正向",
                source_excerpt=f"原文: {rev.original_text}\n修订后: {rev.revised_text}",
                source_location=rev.location,
                pipeline=self.pipeline_id,
                self_confidence=float(fc.get("self_confidence", 0.7)),
                uncertainty_points=(),
                source_filename=doc.filename,
                source_sha256=doc.sha256,
                source_tag=doc.source_tag,
                priority=max(doc.priority, 4),  # fallback 信息低优先级
                contract_types=tuple(doc.contract_types),
                model=self.router.primary.name if self.router.primary else "",
                struct_check_pass=True,
                struct_failures=(),
            ))

        # new_rules → 标准 RuleCandidate
        for rule in obj.get("new_rules", []) or []:
            kws = rule.get("keywords", [])
            if isinstance(kws, str):
                kws = [k.strip() for k in kws.split(",") if k.strip()]
            failures = validate_atomic(rule)
            out.append(RuleCandidate(
                risk_level=str(rule.get("risk_level", "中")),
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
                source_excerpt=rev.revised_text,
                source_location=rev.location,
                pipeline=self.pipeline_id,
                self_confidence=float(rule.get("self_confidence", 0.5)),
                uncertainty_points=tuple(rule.get("uncertainty_points", []) or ()),
                source_filename=doc.filename,
                source_sha256=doc.sha256,
                source_tag=doc.source_tag,
                priority=doc.priority,
                contract_types=tuple(doc.contract_types),
                model=self.router.primary.name if self.router.primary else "",
                struct_check_pass=(len(failures) == 0),
                struct_failures=tuple(failures),
            ))

        return out

    def _render_prompt(
        self, doc: ParsedDocument, rev: RevisionBlock
    ) -> tuple[str, str]:
        theme_keys_text = "\n".join(sorted(THEME_KEYS))
        diff_summary = (
            f"原文长度 {len(rev.original_text)} 字；修订后长度 {len(rev.revised_text)} 字"
        )
        return render_system_user(
            self._prompt,
            system_vars={"theme_keys": theme_keys_text},
            user_vars={
                "filename": doc.filename,
                "location": rev.location,
                "original_text": rev.original_text,
                "revised_text": rev.revised_text,
                "diff_summary": diff_summary,
            },
        )
