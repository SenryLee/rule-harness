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
from ..harness import THEME_KEYS, take_excerpt, validate_atomic
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

        # fallback_clauses 转结构完整的 RuleCandidate（三要素齐全），notes 以 [FALLBACK] 承载替代口径。
        # 若 dedupe 未能并入主规则也会作为低优先级独立规则呈现，必须自身可读、可审计——
        # 不得出现英文 theme_key 叶子泄漏、三要素留空等"半成品"规则。
        for fc in obj.get("fallback_clauses", []) or []:
            theme_key = str(fc.get("theme_key", ""))
            if not theme_key:
                continue
            original_pos = str(fc.get("original_position", "")).strip()
            fallback_pos = str(fc.get("fallback_position", "")).strip()
            subject = str(fc.get("subject", "")).strip()
            topic = theme_key.split(".")[-1]
            change_desc = (
                f"「{original_pos}」→「{fallback_pos}」"
                if (original_pos or fallback_pos)
                else "见原文/修订后对比"
            )
            note = (f"[FALLBACK] 原口径={original_pos}; "
                    f"可接受替代={fallback_pos}; 主体={subject}")
            keywords = tuple(
                k for k in (subject, original_pos, fallback_pos) if k
            )[:5] or (topic,)
            out.append(RuleCandidate(
                risk_level="中",
                keywords=keywords,
                check_item=f"修订变更是否接受：{change_desc}"[:40],
                requirement=(
                    f"[条款] 该条款经修订由「{original_pos}」调整为「{fallback_pos}」，"
                    "审查时确认己方是否接受此变更/让步"
                )[:200],
                notes=note,
                rule_type="clause",
                theme_key=theme_key,
                subject=subject,
                predicate="可接受替代",
                threshold_type="无",
                direction="正向",
                assumption=(
                    f"合同就「{topic}」相关条款存在修订（{change_desc}）且需确认己方立场时适用。"
                ),
                behavior_mode=(
                    f"审查人应核对该条款由「{original_pos}」改为「{fallback_pos}」的变更，"
                    "确认是否为己方可接受的让步。"
                ),
                consequence=(
                    "原文未规定后果；实务风险：未经确认即接受对方修订，"
                    "可能引入不利让步或改变己方权利义务。"
                ),
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
            _take_excerpt_value, _take_excerpt_fallback = take_excerpt(rule, rev.revised_text)
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
                source_excerpt=_take_excerpt_value,
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
                excerpt_fallback=_take_excerpt_fallback,
                raw_block_text=rev.revised_text,
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
