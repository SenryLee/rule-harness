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
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable

from . import storage
from .config import Config, config_to_dict
from .confidence import evaluate_confidence_batch
from .dedupe import build_rule_ids, dedupe_with_priority
from .exporter import (
    _partition_by_target,
    export_change_set,
    export_conflict_report,
    export_discarded_csv,
    export_main_csv,
    export_metadata_csv,
    export_negotiation_csv,
    export_placeholders_csv,
    export_summary_html,
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
                applicable = pipeline.applicable(doc)
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

    def mark_pipeline_done(self, pipeline_id: str, filename: str, rules_emitted: int) -> None:
        state = self.pipeline_progress[pipeline_id]
        file_state = state.files[filename]
        file_state.status = "done"
        file_state.blocks_done = file_state.blocks_total
        file_state.rules_emitted = rules_emitted
        state.files_done += 1
        state.blocks_done += file_state.blocks_done
        state.rules_emitted += rules_emitted
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


def _skip_reason(pipeline_id: str, doc: ParsedDocument) -> str:
    if pipeline_id == "P1":
        if doc.is_passthrough:
            return "直通文件"
        if doc.is_case_doc:
            return "案例文件走 P5"
        if doc.is_redline_doc:
            return "红线文件走 P4"
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
            return doc

    return await asyncio.gather(*[gated(m) for m in file_metas])


# ---------------------------------------------------------------------------
# Phase 2 - pipelines
# ---------------------------------------------------------------------------

async def _run_pipelines(
    docs: list[ParsedDocument],
    router: LLMRouter,
    cfg: Config,
    progress: BatchProgress,
) -> list[RuleCandidate]:
    instances = [P(router, cfg) for P in ALL_PIPELINES]
    progress.prepare_pipeline_progress(docs, instances)

    industry_ctx = (
        cfg.extraction.industry_vocabulary
        + ("\n" + cfg.extraction.industry_focus_points if cfg.extraction.industry_focus_points else "")
    ).strip()

    async def extract_doc(doc: ParsedDocument) -> list[RuleCandidate]:
        candidates: list[RuleCandidate] = []
        applicable = [p for p in instances if p.applicable(doc)]
        ctx = {
            "industry_context": industry_ctx,
            "jurisdiction": "中国大陆",
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
        progress.processed_blocks += len(doc.blocks)
        return candidates

    bundles = await asyncio.gather(*[extract_doc(d) for d in docs])
    flat = [c for bundle in bundles for c in bundle]
    progress.total_rules = len(flat)
    return flat


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
    progress.total_files = len(file_metas)
    progress.status = "running"

    progress.current_step = "parsing"
    docs = await _parse_all(file_metas, batch_dir, progress, cfg.concurrency.files)

    progress.current_step = "extracting"
    candidates = await _run_pipelines(docs, router, cfg, progress)

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
    }


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
