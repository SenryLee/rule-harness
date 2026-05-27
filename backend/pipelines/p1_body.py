from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..harness import THEME_KEYS, validate_atomic
from ..llm import LLMRouter
from ..parsers import ParsedDocument, RuleCandidate
from ..prompt_loader import PromptSections, load_prompt, render_system_user

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "P1_atomic_extract.txt"


class P1BodyPipeline:
    pipeline_id = "P1"

    def __init__(self, router: LLMRouter, cfg: Config):
        self.router = router
        self.cfg = cfg
        self._prompt: PromptSections = load_prompt(PROMPT_PATH)

    def applicable(self, doc: ParsedDocument) -> bool:
        return not doc.is_passthrough and not doc.is_redline_doc

    async def extract(self, doc: ParsedDocument, ctx: dict) -> list[RuleCandidate]:
        sem = asyncio.Semaphore(self.cfg.concurrency.blocks)

        async def process_one(block):
            async with sem:
                return await self._extract_block(doc, block, ctx)

        block_results = await asyncio.gather(
            *[process_one(b) for b in doc.blocks]
        )

        all_rules: list[RuleCandidate] = []
        for block_rules in block_results:
            all_rules.extend(block_rules)
        return all_rules

    async def _extract_block(
        self, doc: ParsedDocument, block, ctx: dict
    ) -> list[RuleCandidate]:
        system_prompt, user_prompt = self._render_prompt(doc, block, ctx)

        try:
            obj = await self.router.chat_json(
                system=system_prompt,
                user=user_prompt,
                temperature=0.2,
            )
        except Exception:
            logger.exception("LLM call failed for block %s in %s", block.block_id, doc.filename)
            return []

        if obj.get("informational"):
            return []

        results: list[RuleCandidate] = []
        for rule in obj.get("rules", []):
            failures = validate_atomic(rule)
            struct_ok = len(failures) == 0

            kws = rule.get("keywords", [])
            if isinstance(kws, str):
                kws = [k.strip() for k in kws.split(",") if k.strip()]

            uncertainty = rule.get("uncertainty_points", [])
            if isinstance(uncertainty, str):
                uncertainty = [u.strip() for u in uncertainty.split(";") if u.strip()]

            candidate = RuleCandidate(
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
                source_excerpt=block.text,
                source_location=block.location,
                pipeline=self.pipeline_id,
                self_confidence=float(rule.get("self_confidence", 0.5)),
                uncertainty_points=tuple(uncertainty),
                source_filename=doc.filename,
                source_sha256=doc.sha256,
                source_tag=doc.source_tag,
                priority=doc.priority,
                contract_types=tuple(doc.contract_types),
                model=self.router.primary.name if self.router.primary else "",
                struct_check_pass=struct_ok,
                struct_failures=tuple(failures),
            )
            results.append(candidate)

        return results

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
        jurisdiction = ctx.get("jurisdiction", "中国大陆")
        contract_types_str = ", ".join(doc.contract_types) if doc.contract_types else "通用"

        return render_system_user(
            self._prompt,
            system_vars={
                "redline_keywords": redline_text,
                "theme_keys": theme_keys_text,
                "industry_context": industry_text,
                "coverage_policy": _coverage_policy(self.cfg),
            },
            user_vars={
                "filename": doc.filename,
                "source_tag": doc.source_tag,
                "priority": str(doc.priority),
                "contract_types": contract_types_str,
                "jurisdiction": jurisdiction,
                "location": block.location,
                "block_text": block.text,
            },
        )


def _coverage_policy(cfg: Config) -> str:
    if cfg.extraction.granularity == "fine":
        granularity = (
            "当前为 fine：以少漏审为优先。每个段落都要寻找可复用审查口径；"
            "同一段存在多个条件、主体、例外、证据点、风险后果时，必须拆成多条原子规则。"
        )
    else:
        granularity = (
            "当前为 balanced：优先抽取稳定、可复用的审查口径；仍需拆分同段内明确独立的条件、主体、阈值和例外。"
        )

    if cfg.extraction.regulation_depth == "full":
        depth = (
            "法规深度为 full：法规、裁判规则、证据规则、效力边界、成立要件、例外条件和审查建议均应规则化；"
            "不得因原文是解释性/分析性文字就跳过。"
        )
    else:
        depth = "法规深度为 limited：保留核心成立要件、禁止性规则和高风险例外。"

    return (
        f"{granularity}\n{depth}\n"
        "- D=0 只能跳过纯背景、目录、事实经过、无可复用审查口径的句子。\n"
        "- 若段落包含裁判摘要、法院认为、法律后果、举证责任、证据适用、合同效力、撤销/解除条件、登记/公示效力等内容，"
        "即使没有'应当/不得'，也要转化为 [条款]/[合规] 审查规则。\n"
        "- 对案例/法律分析文本，输出应围绕'以后审合同时要检查什么、避免什么、补什么证据'，不要只做案情总结。\n"
        "- 没有具体数值时不要编造阈值，threshold_type 使用 无/列表/参照，并在 notes 说明原文依据。"
    )
