from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..harness import THEME_KEYS, take_excerpt, validate_atomic
from ..llm import LLMRouter
from ..parsers import ParsedDocument, RuleCandidate
from .errors import record_llm_failure
from ..prompt_loader import PromptSections, load_prompt, render_system_user

logger = logging.getLogger(__name__)

PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "P5_case_negative_extract.txt"
)


@dataclass(frozen=True)
class CaseChunk:
    text: str
    location: str


class P5CasePipeline:
    pipeline_id = "P5"

    def __init__(self, router: LLMRouter, cfg: Config):
        self.router = router
        self.cfg = cfg
        self._prompt: PromptSections = load_prompt(PROMPT_PATH)

    def applicable(self, doc: ParsedDocument) -> bool:
        return doc.is_case_doc

    async def extract(self, doc: ParsedDocument, ctx: dict) -> list[RuleCandidate]:
        chunks = _case_chunks(doc)
        if not chunks:
            return []

        sem = asyncio.Semaphore(self.cfg.concurrency.blocks)

        async def process_one(chunk: CaseChunk) -> list[RuleCandidate]:
            async with sem:
                return await self._extract_chunk(doc, chunk, ctx)

        chunk_results = await asyncio.gather(*[process_one(chunk) for chunk in chunks])
        results: list[RuleCandidate] = []
        for chunk_rules in chunk_results:
            results.extend(chunk_rules)
        return results

    async def _extract_chunk(
        self, doc: ParsedDocument, chunk: CaseChunk, ctx: dict
    ) -> list[RuleCandidate]:
        system_prompt, user_prompt = self._render_prompt(doc, chunk.text, ctx)

        try:
            obj = await self.router.chat_json(
                system=system_prompt,
                user=user_prompt,
                temperature=0.2,
            )
        except Exception as exc:
            logger.exception("P5 LLM call failed for %s at %s", doc.filename, chunk.location)
            record_llm_failure(ctx, self.pipeline_id, doc.filename, chunk.location, exc)
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

            rule_type = str(rule.get("rule_type", "negative") or "negative")
            direction = str(rule.get("direction", "反向") or "反向")

            _take_excerpt_value, _take_excerpt_fallback = take_excerpt(rule, chunk.text)

            candidate = RuleCandidate(
                risk_level=str(rule.get("risk_level", "高")),
                keywords=tuple(kws),
                check_item=str(rule.get("check_item", "")),
                requirement=str(rule.get("requirement", "")),
                notes=str(rule.get("notes", "")),
                rule_type=rule_type,
                theme_key=str(rule.get("theme_key", "")),
                subject=str(rule.get("subject", "")),
                predicate=str(rule.get("predicate", "")),
                threshold_type=str(rule.get("threshold_type", "列表")),
                direction=direction,
                source_excerpt=_take_excerpt_value,
                source_location=chunk.location,
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
                excerpt_fallback=_take_excerpt_fallback,
                raw_block_text=chunk.text,
            )
            results.append(candidate)

        return results

    def _render_prompt(
        self, doc: ParsedDocument, case_text: str, ctx: dict
    ) -> tuple[str, str]:
        redline_text = ", ".join(self.cfg.extraction.redline_keywords) or "无"
        theme_keys_text = "\n".join(sorted(THEME_KEYS))
        return render_system_user(
            self._prompt,
            system_vars={
                "redline_keywords": redline_text,
                "theme_keys": theme_keys_text,
                "coverage_policy": _coverage_policy(self.cfg),
            },
            user_vars={
                "filename": doc.filename,
                "case_text": case_text,
            },
        )


def _case_chunks(doc: ParsedDocument, max_chars: int = 1800, max_blocks: int = 8) -> list[CaseChunk]:
    chunks: list[CaseChunk] = []
    current: list[str] = []
    start_location = ""
    end_location = ""
    current_chars = 0

    for block in doc.blocks:
        text = block.text.strip()
        if not text:
            continue
        if current and (current_chars + len(text) > max_chars or len(current) >= max_blocks):
            chunks.append(CaseChunk(
                text="\n\n".join(current),
                location=f"{start_location}-{end_location}" if start_location != end_location else start_location,
            ))
            current = []
            current_chars = 0

        if not current:
            start_location = block.location
        current.append(text)
        end_location = block.location
        current_chars += len(text)

    if current:
        chunks.append(CaseChunk(
            text="\n\n".join(current),
            location=f"{start_location}-{end_location}" if start_location != end_location else start_location,
        ))

    return chunks


def count_case_chunks(doc: ParsedDocument) -> int:
    return len(_case_chunks(doc))


def _coverage_policy(cfg: Config) -> str:
    if cfg.extraction.granularity == "fine":
        granularity = "当前为 fine：按高召回抽取，案例分块中每个独立裁判要点、证据要点、效力边界都要规则化。"
    else:
        granularity = "当前为 balanced：抽取稳定、可复用的裁判要点和条款风险。"
    if cfg.extraction.regulation_depth == "full":
        depth = "法规深度为 full：不得只抽反向禁用条款；有效成立条件、举证责任、登记/交付/撤销/解除边界也要输出。"
    else:
        depth = "法规深度为 limited：保留核心败诉原因、无效风险和主要成立条件。"
    return f"{granularity}\n{depth}\n不得编造案号、数字或替代表述；没有案号时 cited_cases=[] 并降低 self_confidence。"
