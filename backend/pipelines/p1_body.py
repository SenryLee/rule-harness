from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..harness import THEME_KEYS, compute_fingerprint, validate_atomic, build_rule_id
from ..llm import LLMRouter
from ..parsers import ParsedDocument, RuleCandidate

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "P1_atomic_extract.txt"


class P1BodyPipeline:
    pipeline_id = "P1"

    def __init__(self, router: LLMRouter, cfg: Config):
        self.router = router
        self.cfg = cfg
        self._prompt_template = PROMPT_PATH.read_text(encoding="utf-8")

    def applicable(self, doc: ParsedDocument) -> bool:
        return not doc.is_passthrough and not doc.is_case_doc and not doc.is_redline_doc

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
        tpl = self._prompt_template

        sys_start = tpl.index("[SYSTEM]") + len("[SYSTEM]")
        sys_end = tpl.index("[USER]")
        system_segment = tpl[sys_start:sys_end].strip()

        user_start = tpl.index("[USER]") + len("[USER]")
        few_shot_start = tpl.index("[FEW-SHOT 1")
        user_segment = tpl[user_start:few_shot_start].strip()

        rest = tpl[few_shot_start:]

        redline_raw = self.cfg.extraction.redline_keywords
        redline_text = ", ".join(redline_raw) if redline_raw else "无"

        theme_keys_text = "\n".join(sorted(THEME_KEYS))

        industry_text = ctx.get("industry_context", "")
        if not industry_text:
            industry_text = self.cfg.extraction.industry_vocabulary or "无"

        system_rendered = system_segment.format(
            redline_keywords=redline_text,
            theme_keys=theme_keys_text,
            industry_context=industry_text,
        )

        jurisdiction = ctx.get("jurisdiction", "中国大陆")
        contract_types_str = ", ".join(doc.contract_types) if doc.contract_types else "通用"

        user_rendered = user_segment.format(
            filename=doc.filename,
            source_tag=doc.source_tag,
            priority=doc.priority,
            contract_types=contract_types_str,
            jurisdiction=jurisdiction,
            location=block.location,
            block_text=block.text,
        )

        full_user = user_rendered + "\n\n" + rest
        return system_rendered, full_user
