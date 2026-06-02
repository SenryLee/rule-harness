"""Batch orchestrator — wires parsers → pipelines → dedupe → confidence → merger → exporter.

This module is the *real* implementation of what ``app.py`` previously stubbed out with
hard-coded regex matching. Each call to :func:`run_batch` performs:

    1. Parse every uploaded file with the right parser (DOCX/PDF/XLSX/TXT).
    2. Run every applicable pipeline (P1/P2/P3/P4/P5/direct) in parallel.
    3. Dedupe with the 5-level source priority and emit conflict flags.
    4. Score combined confidence (self + structure + conflict; consistency on demand).
    5. Compute fingerprints + rule IDs.
    6. Decide merge actions against the SQLite library.
    7. Export the 7-column main CSV, metadata CSV, conflict HTML, change-set CSV,
       and summary HTML.
    8. Persist new/updated rules into the SQLite library.

The public surface is intentionally small — just :func:`run_batch` and the
:class:`BatchProgress` dataclass that the API layer reports on.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable

from . import storage
from .config import Config, config_to_dict
from .confidence import evaluate_confidence_batch
from .dedupe import build_rule_ids, dedupe_with_priority
from .document_profile import profile_document
from .exporter import (
    _partition_by_target,
    export_change_set,
    export_conflict_report,
    export_discarded_csv,
    export_main_csv,
    export_metadata_csv,
    export_negotiation_csv,
    export_out_of_scope_csv,
    export_placeholders_csv,
    export_summary_html,
    export_template_strategy_md,
)
from .harness import build_rule_id, compute_fingerprint
from .llm import LLMRouter, create_llm_router
from .merger import MergeDecision, _encode_rule_for_merge, merge_rule
from .parsers import (
    ParsedDocument,
    RuleCandidate,
    parse_file,
    resolve_source_priority,
)
from .pipelines import ALL_PIPELINES

logger = logging.getLogger(__name__)

PIPELINE_LABELS: dict[str, str] = {
    "P1": "正文抽取",
    "P2": "批注抽取",
    "P3": "修订对比",
    "P4": "谈判红线",
    "P5": "案例反推",
    "direct": "直通转换",
}

PIPELINE_ORDER = ("P1", "P2", "P3", "P4", "P5", "direct")

LOW_OUTPUT_MIN_BLOCKS = 8
LOW_OUTPUT_SPARSE_MIN_BLOCKS = 20
LOW_OUTPUT_MIN_RULES_PER_BLOCK = 0.05


@dataclass
class PipelineFileState:
    filename: str
    status: str = "pending"
    blocks_total: int = 0
    blocks_done: int = 0
    rules_emitted: int = 0
    skip_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "status": self.status,
            "blocks_total": self.blocks_total,
            "blocks_done": self.blocks_done,
            "rules_emitted": self.rules_emitted,
            "skip_reason": self.skip_reason,
        }


@dataclass
class PipelineState:
    label: str
    status: str = "pending"
    files_total: int = 0
    files_done: int = 0
    blocks_total: int = 0
    blocks_done: int = 0
    rules_emitted: int = 0
    skip_reason: str | None = None
    files: dict[str, PipelineFileState] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "status": self.status,
            "files_total": self.files_total,
            "files_done": self.files_done,
            "blocks_total": self.blocks_total,
            "blocks_done": self.blocks_done,
            "rules_emitted": self.rules_emitted,
            "skip_reason": self.skip_reason,
            "files": {name: state.to_dict() for name, state in self.files.items()},
        }


@dataclass
class FidelityStats:
    intercepted: int = 0
    placeholders: int = 0
    discarded: int = 0
    voice_mismatch: int = 0

    def to_dict(self) -> dict:
        return {
            "intercepted": self.intercepted,
            "placeholders": self.placeholders,
            "discarded": self.discarded,
            "voice_mismatch": self.voice_mismatch,
        }


@dataclass
class BatchProgress:
    """Mutable progress descriptor surfaced to the API layer."""

    status: str = "pending"
    current_step: str = "queued"
    total_files: int = 0
    processed_files: int = 0
    total_blocks: int = 0
    processed_blocks: int = 0
    total_rules: int = 0
    tokens_used: int = 0
    errors: list[str] = field(default_factory=list)
    pipeline_progress: dict[str, PipelineState] = field(default_factory=dict)
    fidelity_stats: FidelityStats = field(default_factory=FidelityStats)

    def __post_init__(self) -> None:
        if not self.pipeline_progress:
            self.pipeline_progress = {
                pipeline_id: PipelineState(label=PIPELINE_LABELS[pipeline_id])
                for pipeline_id in PIPELINE_ORDER
            }

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "current_step": self.current_step,
            "total_files": self.total_files,
            "processed_files": self.processed_files,
            "parsed_blocks": self.total_blocks,
            "total_blocks": self.total_blocks,
            "processed_blocks": self.processed_blocks,
            "total_rules": self.total_rules,
            "tokens_used": self.tokens_used,
            "errors": list(self.errors),
            "pipeline_progress": {
                pipeline_id: self.pipeline_progress[pipeline_id].to_dict()
                for pipeline_id in PIPELINE_ORDER
                if pipeline_id in self.pipeline_progress
            },
            "fidelity_stats": self.fidelity_stats.to_dict(),
        }

    def prepare_pipeline_progress(self, docs: list[ParsedDocument], instances: list[object]) -> None:
        for pipeline_id in PIPELINE_ORDER:
            self.pipeline_progress[pipeline_id] = PipelineState(label=PIPELINE_LABELS[pipeline_id])

        by_id = {getattr(p, "pipeline_id"): p for p in instances}
        for pipeline_id in PIPELINE_ORDER:
            pipeline = by_id[pipeline_id]
            state = self.pipeline_progress[pipeline_id]
            skip_reasons: set[str] = set()
            for doc in docs:
                applicable = _pipeline_applicable(pipeline_id, pipeline, doc)
                units = _pipeline_units(pipeline_id, doc) if applicable else 0
                file_state = PipelineFileState(
                    filename=doc.filename,
                    status="pending" if applicable and units > 0 else "skipped",
                    blocks_total=units,
                    skip_reason=None if applicable and units > 0 else _skip_reason(pipeline_id, doc),
                )
                state.files[doc.filename] = file_state
                if applicable and units > 0:
                    state.files_total += 1
                    state.blocks_total += units
                elif file_state.skip_reason:
                    skip_reasons.add(file_state.skip_reason)
            if state.files_total == 0:
                state.status = "skipped"
                state.skip_reason = "；".join(sorted(skip_reasons)) if skip_reasons else "无适用文件"

    def mark_pipeline_running(self, pipeline_id: str, filename: str) -> None:
        state = self.pipeline_progress[pipeline_id]
        file_state = state.files[filename]
        file_state.status = "running"
        state.status = "running"

    def mark_pipeline_block_done(self, pipeline_id: str, filename: str, rules_emitted: int = 0) -> None:
        state = self.pipeline_progress[pipeline_id]
        file_state = state.files[filename]
        if file_state.status == "pending":
            file_state.status = "running"
            state.status = "running"
        if file_state.blocks_done < file_state.blocks_total:
            file_state.blocks_done += 1
            state.blocks_done += 1
            if pipeline_id == "P1":
                self.processed_blocks = min(self.total_blocks, self.processed_blocks + 1)
        file_state.rules_emitted += rules_emitted
        state.rules_emitted += rules_emitted
        self.total_rules += rules_emitted

    def add_token_usage(self, usage: dict | None) -> None:
        if not usage:
            return
        total = usage.get("total_tokens")
        if total is None:
            total = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
        try:
            self.tokens_used += int(total or 0)
        except (TypeError, ValueError):
            return

    def mark_pipeline_done(self, pipeline_id: str, filename: str, rules_emitted: int) -> None:
        state = self.pipeline_progress[pipeline_id]
        file_state = state.files[filename]
        file_state.status = "done"
        remaining_blocks = max(0, file_state.blocks_total - file_state.blocks_done)
        file_state.blocks_done = file_state.blocks_total
        state.blocks_done += remaining_blocks
        if pipeline_id == "P1":
            self.processed_blocks = min(self.total_blocks, self.processed_blocks + remaining_blocks)
        rules_delta = rules_emitted - file_state.rules_emitted
        file_state.rules_emitted = rules_emitted
        state.files_done += 1
        state.rules_emitted += rules_delta
        if state.files_done >= state.files_total:
            state.status = "done"

    def mark_pipeline_failed(self, pipeline_id: str, filename: str, reason: str) -> None:
        state = self.pipeline_progress[pipeline_id]
        file_state = state.files[filename]
        file_state.status = "failed"
        file_state.skip_reason = reason
        state.status = "failed"
        state.skip_reason = reason


@dataclass
class BatchResult:
    batch_id: str
    rules: list[RuleCandidate]
    decisions: list[MergeDecision]
    summary: dict
    exports: dict[str, Path]


# ---------------------------------------------------------------------------
# Phase 1 - parse
# ---------------------------------------------------------------------------

_REDLINE_SOURCE_TAGS = frozenset({"公司红线", "谈判底线"})
_CASE_SOURCE_TAGS = frozenset({"案例", "争议材料"})


def _pipeline_units(pipeline_id: str, doc: ParsedDocument) -> int:
    if pipeline_id in {"P1", "P4"}:
        return len(doc.blocks)
    if pipeline_id == "P2":
        return len(doc.comments)
    if pipeline_id == "P3":
        return len(doc.revisions)
    if pipeline_id == "P5":
        from .pipelines.p5_case import count_case_chunks
        return count_case_chunks(doc)
    if pipeline_id == "direct":
        return len([b for b in doc.blocks if b.block_type == "table_row"])
    return 0


def _pipeline_applicable(pipeline_id: str, pipeline: object, doc: ParsedDocument) -> bool:
    if pipeline_id == "P1":
        return not doc.is_passthrough and len(doc.blocks) > 0
    return bool(pipeline.applicable(doc))


def _skip_reason(pipeline_id: str, doc: ParsedDocument) -> str:
    if pipeline_id == "P1":
        if doc.is_passthrough:
            return "直通文件"
        return "无正文块"
    if pipeline_id == "P2":
        return "无批注"
    if pipeline_id == "P3":
        return "无修订"
    if pipeline_id == "P4":
        return "未标记为红线/谈判底线文件"
    if pipeline_id == "P5":
        return "未标记为案例/争议材料文件"
    if pipeline_id == "direct":
        return "非表格/清单直通文件"
    return "不适用"


async def _parse_one(file_path: Path, meta: dict) -> ParsedDocument:
    """Synchronous parse offloaded to a worker thread (parsers do disk I/O).

    v1.1 修订：原推断使用 ``OR`` 让 ``is_redline=True`` 一旦命中标签集合就 True，
    结果 P4 管道被普通审核手册广泛误触发。改为：用户必须**同时**勾选
    ``is_redline=True`` 且 ``source_tag`` 在红线集合内，P4 才会启用。
    """
    src_tag = meta.get("source_tag", "历史合同")
    user_is_redline = bool(meta.get("is_redline", False))
    user_is_case = bool(meta.get("is_case", False))

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: parse_file(
            filepath=file_path,
            source_tag=src_tag,
            contract_types=list(meta.get("contract_types", []) or []),
            industry_context=meta.get("industry_context"),
            is_scanned=bool(meta.get("is_scanned", False)),
            ocr_enabled=bool(meta.get("ocr_enabled", False)),
            ocr_engine=str(meta.get("ocr_engine", "paddleocr")),
            ocr_language=str(meta.get("ocr_language", "ch+en")),
            # 严格 AND：用户显式勾选 + tag 也对得上
            is_redline=user_is_redline and src_tag in _REDLINE_SOURCE_TAGS,
            is_case=user_is_case and src_tag in _CASE_SOURCE_TAGS,
        ),
    )


async def _parse_all(file_metas: list[dict], batch_dir: Path,
                     progress: BatchProgress, max_concurrency: int) -> list[ParsedDocument]:
    sem = asyncio.Semaphore(max(1, max_concurrency))

    async def gated(meta: dict) -> ParsedDocument:
        async with sem:
            path = batch_dir / meta["filename"]
            try:
                doc = await _parse_one(path, meta)
            except Exception as exc:
                logger.exception("Failed to parse %s", path)
                progress.errors.append(f"parse_failed:{path.name}:{exc}")
                doc = ParsedDocument(
                    sha256="",
                    filename=path.name,
                    source_tag=meta.get("source_tag", "历史合同"),
                    priority=resolve_source_priority(meta.get("source_tag", "历史合同")),
                    contract_types=list(meta.get("contract_types", []) or []),
                    industry_context=None,
                    is_scanned=False,
                    blocks=(),
                    comments=(),
                    revisions=(),
                    is_redline_doc=False,
                    is_case_doc=False,
                    is_passthrough=False,
                )
            progress.processed_files += 1
            progress.total_blocks += len(doc.blocks)
            for warning in getattr(doc, "parse_warnings", ()) or ():
                progress.errors.append(f"parse_warning:{doc.filename}:{warning}")
            return doc

    return await asyncio.gather(*[gated(m) for m in file_metas])


# ---------------------------------------------------------------------------
# Batch task scope
# ---------------------------------------------------------------------------

_TASK_MODE_LABELS = {
    "full_library": "全量规则沉淀",
    "template_focused": "围绕模板抽取",
    "template_strategy": "对我方有利模板生成",
}

_GENERIC_SCOPE_TERMS = {
    "合同", "条款", "双方", "甲方", "乙方", "本合同", "协议", "约定", "应当", "可以",
    "不得", "需要", "相关", "业务", "模板", "内容", "进行", "提供", "包括", "或者",
}


@dataclass(frozen=True)
class TaskScope:
    mode: str
    mode_label: str
    scope_description: str
    our_party: str
    template_text: str
    template_terms: tuple[str, ...]


def _build_task_scope(file_metas: list[dict], docs: list[ParsedDocument]) -> TaskScope:
    first = file_metas[0] if file_metas else {}
    mode = str(first.get("task_mode") or "full_library")
    if mode not in _TASK_MODE_LABELS:
        mode = "full_library"

    scope_description = str(first.get("scope_description") or "").strip()
    our_party = next(
        (
            str(meta.get("our_party"))
            for meta in file_metas
            if meta.get("our_party") and str(meta.get("our_party")) != "通用"
        ),
        str(first.get("our_party") or "通用"),
    )

    template_text = "\n".join(
        block.text
        for doc in docs
        if doc.source_tag == "合同模板"
        for block in doc.blocks
    )
    terms = _extract_scope_terms("\n".join([template_text, scope_description]))
    return TaskScope(
        mode=mode,
        mode_label=_TASK_MODE_LABELS[mode],
        scope_description=scope_description,
        our_party=our_party,
        template_text=template_text,
        template_terms=tuple(terms),
    )


def _extract_scope_terms(text: str) -> list[str]:
    terms: set[str] = set()
    for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9_%]{2,24}", text or ""):
        token = token.strip()
        if not token or token in _GENERIC_SCOPE_TERMS:
            continue
        if len(token) <= 1:
            continue
        terms.add(token)
    return sorted(terms, key=lambda x: (-len(x), x))[:300]


def _apply_task_scope(candidates: list[RuleCandidate], scope: TaskScope) -> list[RuleCandidate]:
    if not candidates:
        return []

    out: list[RuleCandidate] = []
    for rule in candidates:
        match, reason, anchor = _scope_match(rule, scope)
        target = rule.output_target
        if scope.mode in {"template_focused", "template_strategy"} and match == "out_of_scope" and target == "main":
            target = "out_of_scope"
        out.append(replace(
            rule,
            task_mode=scope.mode,
            scope_match=match,
            scope_reason=reason,
            template_anchor=anchor,
            output_target=target,
        ))
    return out


def _scope_match(rule: RuleCandidate, scope: TaskScope) -> tuple[str, str, str]:
    if scope.mode == "full_library":
        return "in_scope", "全量规则沉淀模式，不做模板相关性过滤", ""

    if rule.source_tag == "合同模板":
        return "in_scope", "规则直接来自本次合同模板", rule.source_filename

    searchable = "\n".join([
        rule.check_item,
        rule.requirement,
        rule.notes,
        " ".join(rule.keywords),
        rule.theme_key.replace(".", " "),
    ])
    keyword_hits = [
        kw for kw in rule.keywords
        if kw and len(kw) >= 2 and kw in scope.template_text
    ]
    term_hits = [
        term for term in scope.template_terms
        if term and term in searchable
    ][:5]

    hits = keyword_hits[:5] or term_hits
    if hits:
        return "in_scope", f"命中模板相关词: {'、'.join(hits)}", "、".join(hits)

    if scope.scope_description:
        desc_terms = _extract_scope_terms(scope.scope_description)
        desc_hits = [term for term in desc_terms if term in searchable][:5]
        if desc_hits:
            return "in_scope", f"命中用户范围说明: {'、'.join(desc_hits)}", "、".join(desc_hits)

    return "out_of_scope", "未命中本次模板文本或用户范围说明", ""


# ---------------------------------------------------------------------------
# Phase 2 - pipelines
# ---------------------------------------------------------------------------

async def _run_pipelines(
    docs: list[ParsedDocument],
    router: LLMRouter,
    cfg: Config,
    progress: BatchProgress,
    scope: TaskScope | None = None,
) -> list[RuleCandidate]:
    instances = [P(router, cfg) for P in ALL_PIPELINES]
    progress.prepare_pipeline_progress(docs, instances)

    industry_ctx = (
        cfg.extraction.industry_vocabulary
        + ("\n" + cfg.extraction.industry_focus_points if cfg.extraction.industry_focus_points else "")
    ).strip()

    async def extract_doc(doc: ParsedDocument) -> list[RuleCandidate]:
        candidates: list[RuleCandidate] = []
        applicable = [
            p for p in instances
            if _pipeline_applicable(p.pipeline_id, p, doc)
        ]
        document_profile = _document_profile_for_doc(doc)
        ctx = {
            "industry_context": industry_ctx,
            "jurisdiction": "中国大陆",
            "progress": progress,
            "task_mode": scope.mode if scope else "full_library",
            "task_mode_label": scope.mode_label if scope else "全量规则沉淀",
            "scope_description": scope.scope_description if scope else "",
            "our_party": scope.our_party if scope else "通用",
            "document_profile": document_profile,
            "document_profile_text": _format_document_profile(document_profile),
        }

        async def run_one(pipeline) -> list[RuleCandidate]:
            pipeline_id = pipeline.pipeline_id
            units = _pipeline_units(pipeline_id, doc)
            if units <= 0:
                return []
            progress.mark_pipeline_running(pipeline_id, doc.filename)
            try:
                out = await pipeline.extract(doc, ctx)
            except Exception as exc:
                logger.exception("Pipeline failed for %s: %s", doc.filename, exc)
                progress.errors.append(f"pipeline_failed:{doc.filename}:{exc}")
                progress.mark_pipeline_failed(pipeline_id, doc.filename, str(exc))
                return []
            progress.mark_pipeline_done(pipeline_id, doc.filename, len(out))
            return out

        results = await asyncio.gather(*[run_one(p) for p in applicable])
        for r in results:
            candidates.extend(r)
        return candidates

    bundles = await asyncio.gather(*[extract_doc(d) for d in docs])
    flat = [c for bundle in bundles for c in bundle]
    progress.total_rules = len(flat)
    return flat


def _document_profile_for_doc(doc: ParsedDocument) -> dict:
    preview_text = "\n".join(block.text for block in doc.blocks[:80])
    return profile_document(doc.filename, preview_text[:20000])


def _format_document_profile(profile: dict) -> str:
    scenarios = profile.get("secondary_scenarios") or []
    if isinstance(scenarios, str):
        scenarios_text = scenarios
    else:
        scenarios_text = "、".join(str(item) for item in scenarios if item)
    return "\n".join([
        f"资料体裁：{profile.get('document_type', '未识别')}",
        f"权威层级：{profile.get('authority_level', '未识别')}",
        f"主法律主题：{profile.get('primary_legal_topic', '未识别')}",
        f"辅助场景：{scenarios_text or '无'}",
        f"处理建议：{profile.get('processing_suggestion', '无')}",
        f"分类置信：{profile.get('classification_mode', 'unknown')} ({profile.get('confidence', 0)})",
        "注意：资料画像只用于理解语境，不得据此减少基础正文抽取覆盖。",
    ])


# ---------------------------------------------------------------------------
# Phase 3-5 - dedupe / confidence / rule_id
# ---------------------------------------------------------------------------

def _finalize(candidates: list[RuleCandidate], cfg: Config) -> list[RuleCandidate]:
    """Dedupe → fidelity → confidence → assign IDs. Pure-CPU, no LLM."""
    deduped = dedupe_with_priority(candidates, cfg)
    checked = _apply_fidelity_gate(deduped)
    scored = evaluate_confidence_batch(checked, cfg)
    return build_rule_ids(scored)


def _update_fidelity_stats(progress: BatchProgress, rules: list[RuleCandidate]) -> None:
    progress.fidelity_stats = FidelityStats(
        intercepted=sum(1 for r in rules if not r.fidelity_pass),
        placeholders=sum(1 for r in rules if r.output_target == "placeholder"),
        discarded=sum(1 for r in rules if r.output_target == "discarded"),
        voice_mismatch=sum(1 for r in rules if not r.voice_match),
    )


def _apply_fidelity_gate(candidates: list[RuleCandidate]) -> list[RuleCandidate]:
    """v1.1 第五重门 + 语态校验 + 占位规则分流。

    一条候选规则的最终 ``output_target`` 决策表（按优先级从上到下）：

        条件                                          → output_target
        ----------------------------------------------- ----------------
        fidelity 失败 token 数 ≥ 2                    → "discarded"
        是占位规则（is_placeholder_rule）             → "placeholder"
        以上都不是                                    → 保持原值（默认 "main"）

    同时记录：
      - ``fidelity_pass`` + ``fidelity_failures``
      - ``voice_match``（软语态原文却写了强义务 → False）
    """
    from .fidelity import check_fidelity
    from .voice_check import check_voice_match
    from .placeholder_detector import is_placeholder_rule

    out: list[RuleCandidate] = []
    for rule in candidates:
        result = check_fidelity(
            requirement=rule.requirement,
            check_item=rule.check_item,
            notes=rule.notes,
            source_excerpt=rule.source_excerpt,
        )
        voice_failures = check_voice_match(rule.source_excerpt, rule.requirement)

        new_target = rule.output_target
        if not result.passed and len(result.failures) >= 2:
            new_target = "discarded"
        elif is_placeholder_rule(
            requirement=rule.requirement,
            notes=rule.notes,
            threshold_type=rule.threshold_type,
            self_confidence=rule.self_confidence,
            source_excerpt=rule.source_excerpt,
        ):
            new_target = "placeholder"

        out.append(
            replace(
                rule,
                fidelity_pass=result.passed,
                fidelity_failures=result.failures,
                voice_match=(len(voice_failures) == 0),
                output_target=new_target,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Phase 6 - merge decisions against SQLite
# ---------------------------------------------------------------------------

def _decide_merges(rules: list[RuleCandidate], batch_id: str) -> list[MergeDecision]:
    decisions: list[MergeDecision] = []
    for rule in rules:
        try:
            decision = merge_rule(rule, batch_id, storage=storage)
        except Exception:
            logger.exception("merge_rule failed for %s", rule.rule_id)
            # fall back to a `new` decision so the export still shows it
            decision = MergeDecision(
                rule_id=rule.rule_id,
                action="new",
                new_rule=_encode_rule_for_merge(rule),
                old_rule=None,
                diff=None,
                reason="merge error (default to new)",
            )
        decisions.append(decision)
    return decisions


# ---------------------------------------------------------------------------
# Phase 7 - exports
# ---------------------------------------------------------------------------

def _do_exports(
    rules: list[RuleCandidate],
    decisions: list[MergeDecision],
    batch_id: str,
    exports_dir: Path,
) -> dict[str, Path]:
    """v1.1: 按 output_target 分桶导出。

    主 CSV 只含实质规则；占位规则进 placeholders.csv；忠实度严重失败的进
    discarded.csv；P4 阶梯进 negotiation.csv。元数据 / 冲突报告 / 摘要等
    仍覆盖全部规则（含分类标记）。
    """
    exports_dir.mkdir(parents=True, exist_ok=True)
    buckets = _partition_by_target(rules)

    paths: dict[str, Path] = {
        "main_csv": exports_dir / "main.csv",
        "metadata_csv": exports_dir / "metadata.csv",
        "conflict_report": exports_dir / "conflict_report.html",
        "change_set": exports_dir / "change_set.csv",
        "summary_html": exports_dir / "summary.html",
    }

    export_main_csv(buckets.get("main", []), paths["main_csv"])
    export_metadata_csv(rules, paths["metadata_csv"])
    export_conflict_report(rules, batch_id, paths["conflict_report"])
    export_change_set(decisions, paths["change_set"])
    export_summary_html(rules, batch_id, None, paths["summary_html"])

    # 仅在对应桶非空时导出，避免空文件污染
    if buckets.get("placeholder"):
        paths["placeholders_csv"] = exports_dir / "placeholders.csv"
        export_placeholders_csv(buckets["placeholder"], paths["placeholders_csv"])
    if buckets.get("discarded"):
        paths["discarded_csv"] = exports_dir / "discarded.csv"
        export_discarded_csv(buckets["discarded"], paths["discarded_csv"])
    if buckets.get("negotiation"):
        paths["negotiation_csv"] = exports_dir / "negotiation.csv"
        export_negotiation_csv(buckets["negotiation"], paths["negotiation_csv"])
    if buckets.get("out_of_scope"):
        paths["out_of_scope_csv"] = exports_dir / "out_of_scope.csv"
        export_out_of_scope_csv(buckets["out_of_scope"], paths["out_of_scope_csv"])
    if any(getattr(rule, "task_mode", "") == "template_strategy" for rule in rules):
        paths["template_strategy_md"] = exports_dir / "template_strategy.md"
        export_template_strategy_md(rules, paths["template_strategy_md"])

    return paths


# ---------------------------------------------------------------------------
# Phase 8 - persist
# ---------------------------------------------------------------------------

def _persist(rules: list[RuleCandidate], decisions: list[MergeDecision], batch_id: str,
             cfg: Config) -> None:
    try:
        storage.insert_batch({
            "batch_id": batch_id,
            "config_snapshot": json.dumps(_sanitized_cfg(cfg), ensure_ascii=False),
        })
    except Exception:
        logger.exception("insert_batch failed; continuing")

    for rule in rules:
        decision = next((d for d in decisions if d.rule_id == rule.rule_id), None)
        action = decision.action if decision else "new"
        try:
            if action == "new":
                # 双保险：merge_rule 可能因 storage 异常误报 new；这里再查一次。
                if storage.find_rule_by_id(rule.rule_id) is None:
                    storage.insert_rule(_encode_rule_for_merge(rule), batch_id)
                    storage.insert_rule_metadata(_metadata_payload(rule))
            elif action == "update":
                storage.update_rule(rule.rule_id, _encode_rule_for_merge(rule), batch_id)
            elif action == "add_variant":
                storage.add_variant(rule.rule_id, _encode_rule_for_merge(rule))
            # skip / conflict: 主库保持不变
        except Exception:
            logger.exception("persist failed for rule %s (%s)", rule.rule_id, action)

        try:
            storage.record_merge_history(
                batch_id=batch_id,
                rule_id=rule.rule_id,
                action=action,
                diff_payload=(
                    json.dumps(decision.diff, ensure_ascii=False)
                    if decision and decision.diff
                    else None
                ),
            )
        except Exception:
            logger.exception("record_merge_history failed for %s", rule.rule_id)


def _metadata_payload(rule: RuleCandidate) -> dict:
    return {
        "rule_id": rule.rule_id,
        "rule_type": rule.rule_type,
        "applicable_contracts": ", ".join(rule.contract_types),
        "jurisdiction": rule.jurisdiction,
        "source_filename": rule.source_filename,
        "source_sha256": rule.source_sha256,
        "source_location": rule.source_location,
        "source_excerpt": rule.source_excerpt[:500],
        "pipeline": rule.pipeline,
        "model": rule.model,
        "self_confidence": rule.self_confidence,
        "consistency_confidence": None,
        "struct_check_pass": rule.struct_check_pass,
        "conflict_flag": rule.conflict_flag,
        "combined_confidence": rule.combined_confidence,
        "theme_key": rule.theme_key,
        "ladder_preferred": rule.ladder.get("preferred", "") if rule.ladder else "",
        "ladder_acceptable": rule.ladder.get("acceptable", "") if rule.ladder else "",
        "ladder_unacceptable": rule.ladder.get("unacceptable", "") if rule.ladder else "",
        "cited_cases": ", ".join(rule.cited_cases) if rule.cited_cases else "",
        "parent_rule_id": "",
        "variant_versions": rule.variant_versions,
        # v1.1
        "fidelity_pass": rule.fidelity_pass,
        "fidelity_failures": ", ".join(rule.fidelity_failures),
        "voice_match": rule.voice_match,
        "output_target": rule.output_target,
        "task_mode": rule.task_mode,
        "scope_match": rule.scope_match,
        "scope_reason": rule.scope_reason,
        "template_anchor": rule.template_anchor,
        "assumption": rule.assumption,
        "behavior_mode": rule.behavior_mode,
        "consequence": rule.consequence,
        "exception_conditions": rule.exception_conditions,
        "review_action": rule.review_action,
        "transformation_note": rule.transformation_note,
    }


def _sanitized_cfg(cfg: Config) -> dict:
    """Snapshot of config without api_key — never persist secrets to history."""
    raw = config_to_dict(cfg)
    for slot in ("primary", "fallback"):
        if slot in raw.get("models", {}) and "api_key" in raw["models"][slot]:
            raw["models"][slot]["api_key"] = "***"
    return raw


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run_batch(
    batch_id: str,
    file_metas: list[dict],
    batch_dir: Path,
    exports_dir: Path,
    cfg: Config,
    progress: BatchProgress,
) -> BatchResult:
    """End-to-end batch execution.

    The caller (``app.py``) is responsible for storing files on disk and creating
    a :class:`BatchProgress` instance whose ``status`` will be flipped to ``success``
    or ``partial`` here.
    """
    router = create_llm_router(cfg)
    router.usage_callback = progress.add_token_usage
    progress.total_files = len(file_metas)
    progress.status = "running"
    parse_metas = [
        {
            **meta,
            "ocr_enabled": cfg.ocr.enabled or bool(meta.get("is_scanned", False)),
            "ocr_engine": cfg.ocr.engine,
            "ocr_language": cfg.ocr.language,
        }
        for meta in file_metas
    ]

    progress.current_step = "parsing"
    docs = await _parse_all(parse_metas, batch_dir, progress, cfg.concurrency.files)
    scope = _build_task_scope(file_metas, docs)

    progress.current_step = "extracting"
    candidates = await _run_pipelines(docs, router, cfg, progress, scope)
    candidates = _apply_task_scope(candidates, scope)

    progress.current_step = "finalizing"
    rules = _finalize(candidates, cfg)
    progress.total_rules = len(rules)
    _update_fidelity_stats(progress, rules)

    progress.current_step = "merging"
    decisions = _decide_merges(rules, batch_id)

    progress.current_step = "exporting"
    exports = _do_exports(rules, decisions, batch_id, exports_dir)

    progress.current_step = "persisting"
    _persist(rules, decisions, batch_id, cfg)

    progress.current_step = "done"
    progress.status = "success" if not progress.errors else "partial"

    summary = _build_summary(rules, decisions, progress)
    return BatchResult(
        batch_id=batch_id,
        rules=rules,
        decisions=decisions,
        summary=summary,
        exports=exports,
    )


def _build_summary(
    rules: list[RuleCandidate],
    decisions: list[MergeDecision],
    progress: BatchProgress,
) -> dict:
    by_risk: dict[str, int] = {"高": 0, "中": 0, "低": 0}
    by_pipeline: dict[str, int] = {}
    by_type: dict[str, int] = {}
    low_conf = 0
    conflicts = 0
    for r in rules:
        by_risk[r.risk_level] = by_risk.get(r.risk_level, 0) + 1
        by_pipeline[r.pipeline] = by_pipeline.get(r.pipeline, 0) + 1
        by_type[r.rule_type] = by_type.get(r.rule_type, 0) + 1
        if r.combined_confidence < 0.7:
            low_conf += 1
        if r.conflict_flag != "无":
            conflicts += 1

    actions: dict[str, int] = {}
    for d in decisions:
        actions[d.action] = actions.get(d.action, 0) + 1

    return {
        "total_rules": len(rules),
        "by_risk": by_risk,
        "by_pipeline": by_pipeline,
        "by_type": by_type,
        "low_confidence": low_conf,
        "conflicts": conflicts,
        "merge_actions": actions,
        "errors": list(progress.errors),
        "extraction_completeness": _build_extraction_completeness(rules, progress),
    }


def _build_extraction_completeness(
    rules: list[RuleCandidate],
    progress: BatchProgress,
) -> dict:
    rules_per_file = _rules_per_file(rules, progress)
    return {
        "parsed_blocks": progress.total_blocks,
        "total_blocks": progress.total_blocks,
        "rules_per_file": rules_per_file,
        "low_output_files": _low_output_files(rules_per_file, progress),
        "pipeline_coverage": _pipeline_coverage(progress),
    }


def _rules_per_file(rules: list[RuleCandidate], progress: BatchProgress) -> dict[str, int]:
    filenames: set[str] = set()
    for state in progress.pipeline_progress.values():
        filenames.update(state.files)

    counts = {filename: 0 for filename in filenames}
    for rule in rules:
        filename = rule.source_filename or "(unknown)"
        counts[filename] = counts.get(filename, 0) + 1
    return dict(sorted(counts.items()))


def _low_output_files(rules_per_file: dict[str, int], progress: BatchProgress) -> list[dict]:
    p1_files = progress.pipeline_progress.get("P1", PipelineState(label=PIPELINE_LABELS["P1"])).files
    low_files: list[dict] = []

    for filename, rules_count in sorted(rules_per_file.items()):
        p1_state = p1_files.get(filename)
        if not p1_state:
            continue

        blocks_total = p1_state.blocks_total
        if blocks_total < LOW_OUTPUT_MIN_BLOCKS:
            continue

        reasons: list[str] = []
        if rules_count == 0:
            reasons.append("no_rules")
        elif (
            blocks_total >= LOW_OUTPUT_SPARSE_MIN_BLOCKS
            and rules_count / blocks_total < LOW_OUTPUT_MIN_RULES_PER_BLOCK
        ):
            reasons.append("sparse_rules")

        if p1_state.rules_emitted == 0:
            reasons.append("basic_body_no_rules")

        if reasons:
            low_files.append({
                "filename": filename,
                "blocks_total": blocks_total,
                "rules": rules_count,
                "p1_rules": p1_state.rules_emitted,
                "reasons": reasons,
            })

    return low_files


def _pipeline_coverage(progress: BatchProgress) -> dict[str, dict]:
    coverage: dict[str, dict] = {}
    for pipeline_id in PIPELINE_ORDER:
        state = progress.pipeline_progress.get(pipeline_id)
        if not state:
            continue
        coverage[pipeline_id] = {
            "label": state.label,
            "status": state.status,
            "files_total": state.files_total,
            "files_done": state.files_done,
            "blocks_total": state.blocks_total,
            "blocks_done": state.blocks_done,
            "rules_emitted": state.rules_emitted,
        }
    return coverage


# ---------------------------------------------------------------------------
# Public helpers reused by the API layer
# ---------------------------------------------------------------------------

def candidate_to_api_dict(rule: RuleCandidate) -> dict:
    """Serialize a RuleCandidate for the JSON API."""
    return {
        "rule_id": rule.rule_id,
        "enabled": rule.enabled,
        "risk_level": rule.risk_level,
        "keywords": list(rule.keywords),
        "check_item": rule.check_item,
        "requirement": rule.requirement,
        "notes": rule.notes,
        "rule_type": rule.rule_type,
        "theme_key": rule.theme_key,
        "subject": rule.subject,
        "predicate": rule.predicate,
        "threshold_type": rule.threshold_type,
        "direction": rule.direction,
        "fingerprint": rule.fingerprint,
        "source_file": rule.source_filename,
        "source_tag": rule.source_tag,
        "source_excerpt": rule.source_excerpt,
        "source_location": rule.source_location,
        "pipeline": rule.pipeline,
        "model": rule.model,
        "priority": rule.priority,
        "contract_types": list(rule.contract_types),
        "self_confidence": rule.self_confidence,
        "combined_confidence": rule.combined_confidence,
        "confidence": rule.combined_confidence,  # backwards-compat alias
        "struct_check_pass": rule.struct_check_pass,
        "struct_failures": list(rule.struct_failures),
        "conflict_flag": rule.conflict_flag,
        "has_conflict": rule.conflict_flag != "无",
        "variant_versions": rule.variant_versions,
        "ladder": rule.ladder,
        "cited_cases": list(rule.cited_cases) if rule.cited_cases else [],
        "uncertainty_points": list(rule.uncertainty_points),
        "jurisdiction": rule.jurisdiction,
        # v1.1
        "fidelity_pass": rule.fidelity_pass,
        "fidelity_failures": list(rule.fidelity_failures),
        "voice_match": rule.voice_match,
        "output_target": rule.output_target,
        "task_mode": rule.task_mode,
        "scope_match": rule.scope_match,
        "scope_reason": rule.scope_reason,
        "template_anchor": rule.template_anchor,
        "assumption": rule.assumption,
        "behavior_mode": rule.behavior_mode,
        "consequence": rule.consequence,
        "exception_conditions": rule.exception_conditions,
        "review_action": rule.review_action,
        "transformation_note": rule.transformation_note,
    }


def decision_to_api_dict(decision: MergeDecision) -> dict:
    return {
        "rule_id": decision.rule_id,
        "action": decision.action,
        "reason": decision.reason,
        "diff": decision.diff,
        "fingerprint": decision.new_rule.get("fingerprint", ""),
        "check_item": decision.new_rule.get("check_item", ""),
    }
