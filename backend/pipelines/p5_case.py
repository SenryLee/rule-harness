from __future__ import annotations

import logging
from pathlib import Path

from ..config import Config
from ..harness import THEME_KEYS, validate_atomic
from ..llm import LLMRouter
from ..parsers import ParsedDocument, RuleCandidate

logger = logging.getLogger(__name__)

PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "P5_case_negative_extract.txt"
)


class P5CasePipeline:
    pipeline_id = "P5"

    def __init__(self, router: LLMRouter, cfg: Config):
        self.router = router
        self.cfg = cfg
        self._prompt_template = PROMPT_PATH.read_text(encoding="utf-8")

    def applicable(self, doc: ParsedDocument) -> bool:
        return doc.is_case_doc

    async def extract(self, doc: ParsedDocument, ctx: dict) -> list[RuleCandidate]:
        full_text_parts = [b.text for b in doc.blocks]
        combined_text = "\n\n".join(full_text_parts)

        if not combined_text.strip():
            return []

        system_prompt, user_prompt = self._render_prompt(doc, combined_text, ctx)

        try:
            obj = await self.router.chat_json(
                system=system_prompt,
                user=user_prompt,
                temperature=0.2,
            )
        except Exception:
            logger.exception("P5 LLM call failed for %s", doc.filename)
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

            cited = rule.get("cited_cases", [])
            if isinstance(cited, str):
                cited = [c.strip() for c in cited.split(";") if c.strip()]

            candidate = RuleCandidate(
                risk_level=str(rule.get("risk_level", "高")),
                keywords=tuple(kws),
                check_item=str(rule.get("check_item", "")),
                requirement=str(rule.get("requirement", "")),
                notes=str(rule.get("notes", "")),
                rule_type="negative",
                theme_key=str(rule.get("theme_key", "")),
                subject=str(rule.get("subject", "")),
                predicate=str(rule.get("predicate", "")),
                threshold_type=str(rule.get("threshold_type", "列表")),
                direction="反向",
                source_excerpt=combined_text[:500],
                source_location="full_case",
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
                cited_cases=tuple(cited) if cited else None,
            )
            results.append(candidate)

        return results

    def _render_prompt(
        self, doc: ParsedDocument, case_text: str, ctx: dict
    ) -> tuple[str, str]:
        tpl = self._prompt_template

        sys_start = tpl.index("[SYSTEM]") + len("[SYSTEM]")
        sys_end = tpl.index("[USER]")
        system_segment = tpl[sys_start:sys_end].strip()

        user_start = tpl.index("[USER]") + len("[USER]")
        few_shot_start = tpl.index("[FEW-SHOT]")
        user_segment = tpl[user_start:few_shot_start].strip()

        rest = tpl[few_shot_start:]

        redline_raw = self.cfg.extraction.redline_keywords
        redline_text = ", ".join(redline_raw) if redline_raw else "无"
        theme_keys_text = "\n".join(sorted(THEME_KEYS))

        system_rendered = system_segment.format(
            redline_keywords=redline_text,
            theme_keys=theme_keys_text,
        )

        user_rendered = user_segment.format(
            filename=doc.filename,
            case_text=case_text,
        )

        full_user = user_rendered + "\n\n" + rest
        return system_rendered, full_user
