from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from ..config import Config
from ..harness import THEME_KEYS, compute_fingerprint, build_rule_id, validate_atomic
from ..llm import LLMRouter
from ..parsers import ParsedDocument, RuleCandidate, map_passthrough_row_to_fields, normalize_risk_label
from ..prompt_loader import PromptSections, load_prompt, render_system_user

logger = logging.getLogger(__name__)

KEYWORD_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "KEYWORD_expand.txt"
)

_COLUMN_ALIASES: list[tuple[frozenset[str], str]] = [
    (frozenset({"关键词", "关键字", "触发词", "关键词汇", "keywords"}), "keywords"),
    (frozenset({"检查项", "检查内容", "检查要点", "检查", "check_item"}), "check_item"),
    (
        frozenset({"审查要求", "要求", "审查标准", "标准要求", "合规要求", "审查", "requirement"}),
        "requirement",
    ),
    (
        frozenset({"审查说明", "说明", "备注", "审查建议", "建议", "补充说明", "notes"}),
        "notes",
    ),
    (
        frozenset({"风险程度", "风险等级", "风险", "风险分类", "risk_level"}),
        "risk_level",
    ),
    (
        frozenset({"适用合同类型", "合同类型", "适用类型", "contract_type"}),
        "contract_type",
    ),
]


class DirectPassthroughPipeline:
    pipeline_id = "direct"

    def __init__(self, router: LLMRouter, cfg: Config):
        self.router = router
        self.cfg = cfg
        self._kw_prompt: PromptSections = load_prompt(KEYWORD_PROMPT_PATH)

    def applicable(self, doc: ParsedDocument) -> bool:
        return doc.is_passthrough

    async def extract(self, doc: ParsedDocument, ctx: dict) -> list[RuleCandidate]:
        results: list[RuleCandidate] = []
        column_map = self._build_column_map(doc)

        for block in doc.blocks:
            if block.block_type != "table_row":
                continue

            fields = map_passthrough_row_to_fields(block.text, [])
            if not fields:
                continue

            candidate = self._row_to_candidate(block, fields, doc, ctx)
            results.append(candidate)

        return results

    def _build_column_map(self, doc: ParsedDocument) -> dict[str, str]:
        column_map: dict[str, str] = {}
        if not doc.blocks:
            return column_map

        first_row = doc.blocks[0]
        if first_row.block_type != "table_row":
            return column_map

        pairs = first_row.text.split("; ")
        for pair in pairs:
            if ": " not in pair:
                continue
            header, value = pair.split(": ", 1)
            header_norm = header.strip()
            for aliases, field_name in _COLUMN_ALIASES:
                for alias in aliases:
                    if alias in header_norm:
                        column_map[header_norm] = field_name
                        break

        return column_map

    def _row_to_candidate(
        self,
        block,
        fields: dict[str, str],
        doc: ParsedDocument,
        ctx: dict,
    ) -> RuleCandidate:
        risk_raw = fields.get("risk_level", "中")
        risk_level = normalize_risk_label(risk_raw)

        keywords_raw = fields.get("keywords", "")
        kws = _split_keywords(keywords_raw)

        check_item = (fields.get("check_item", "") or "")[:30]
        requirement_raw = fields.get("requirement", "")
        notes_raw = (fields.get("notes", "") or "")[:500]

        requirement = _ensure_requirement_tag(requirement_raw)[:200]
        rule_type = "governance" if requirement.startswith("[合规]") else "clause"
        theme_key = self._infer_theme_key(check_item, requirement)

        # 关键词兜底：当 Excel 单元格未填关键词时，至少注入 1 个，避免 validate_atomic 失败
        if not kws:
            seed = check_item or theme_key.split(".")[-1]
            if seed:
                kws = [seed]

        candidate_dict = {
            "risk_level": risk_level,
            "keywords": list(kws),
            "check_item": check_item,
            "requirement": requirement,
            "notes": notes_raw,
            "theme_key": theme_key,
        }
        failures = validate_atomic(candidate_dict)

        return RuleCandidate(
            risk_level=risk_level,
            keywords=tuple(kws),
            check_item=check_item,
            requirement=requirement,
            notes=notes_raw,
            rule_type=rule_type,
            theme_key=theme_key,
            subject="双方",
            predicate="应符合",
            threshold_type="无",
            direction="正向",
            source_excerpt=block.text,
            source_location=block.location,
            pipeline=self.pipeline_id,
            self_confidence=0.85,
            uncertainty_points=(),
            source_filename=doc.filename,
            source_sha256=doc.sha256,
            source_tag=doc.source_tag,
            priority=doc.priority,
            contract_types=tuple(doc.contract_types),
            model="passthrough",
            struct_check_pass=(len(failures) == 0),
            struct_failures=tuple(failures),
        )

    def _infer_theme_key(self, check_item: str, requirement: str) -> str:
        """Best-effort match against the theme whitelist.

        Walks every known key and checks whether any of its components appear
        in ``check_item + requirement``. Falls back to ``compliance.custom`` so
        the row is at least surfaced for human review.
        """
        text = (check_item + " " + requirement).lower()
        best: tuple[int, str] = (0, "")
        for key in THEME_KEYS:
            score = sum(1 for part in key.split(".") if part and part in text)
            if score > best[0]:
                best = (score, key)
        return best[1] or "compliance.custom"

    async def _expand_keywords(
        self, excerpt: str, primary_kws: str, contract_types: str
    ) -> list[str]:
        try:
            system_seg, user_rendered = render_system_user(
                self._kw_prompt,
                system_vars={},
                user_vars={
                    "excerpt": excerpt,
                    "primary_keywords": primary_kws,
                    "contract_types": contract_types,
                },
            )
            obj = await self.router.chat_json(
                system=system_seg,
                user=user_rendered,
                temperature=0.1,
            )
            return obj.get("keywords", [])
        except Exception:
            logger.exception("KEYWORD_expand call failed")
            return []


def _split_keywords(raw: str) -> list[str]:
    if not raw:
        return []
    if "," in raw or "，" in raw:
        parts = re.split(r"[,，;；]", raw)
    elif "、" in raw:
        parts = raw.split("、")
    else:
        parts = raw.split()
    return [p.strip() for p in parts if p.strip()]


def _ensure_requirement_tag(text: str) -> str:
    if not text:
        return "[条款]"
    if text.startswith("[条款]") or text.startswith("[合规]"):
        return text
    return f"[合规] {text}" if any(
        kw in text for kw in ("应当", "必须", "需", "应", "审批", "备案", "流程")
    ) else f"[条款] {text}"
