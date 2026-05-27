"""Confidence scoring — the harness §5 "four-gate" pipeline.

Gate 1: model self-confidence (always)
Gate 2: multi-sample consistency (only on demand — see :func:`apply_consistency`)
Gate 3: structural-check pass / fail
Gate 4: conflict flag from dedupe

The combined score is a weighted average controlled by ``cfg.confidence.weights``.
A rule with ``combined_confidence < cfg.confidence.threshold_review`` is the
"please human-review me" signal surfaced in the HTML reports.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

from .config import Config
from .harness import compute_fingerprint
from .llm import LLMRouter
from .parsers import RuleCandidate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gate aggregation
# ---------------------------------------------------------------------------

def evaluate_confidence(rule: RuleCandidate, cfg: Config) -> RuleCandidate:
    """综合置信度 = 自评 + 一致性 + 结构 + 冲突 + **忠实度**（v1.1 新增第五重门）。

    cfg.confidence.weights 现在含 5 项；为兼容旧 yaml（只配 4 项），未配置的
    ``fidelity`` 权重缺省取 0.30，并把现有 4 项按比例缩到 0.70（详见
    :func:`_resolve_weights`）。
    """
    weights = _resolve_weights(cfg)
    self_score = _clamp01(rule.self_confidence)
    consistency_score = self_score  # apply_consistency() 会覆盖
    struct_score = 1.0 if rule.struct_check_pass else 0.0
    conflict_score = 1.0 if rule.conflict_flag == "无" else 0.0
    fidelity_score = 1.0 if rule.fidelity_pass else 0.0

    combined = (
        weights["self"] * self_score
        + weights["consistency"] * consistency_score
        + weights["struct"] * struct_score
        + weights["conflict"] * conflict_score
        + weights["fidelity"] * fidelity_score
    )
    return replace(rule, combined_confidence=round(_clamp01(combined), 4))


def _resolve_weights(cfg: Config) -> dict[str, float]:
    """读出 5 项权重，对仍是 4 项的旧配置自动迁移。"""
    w = cfg.confidence.weights
    base = {
        "self": float(w.self_),
        "consistency": float(w.consistency),
        "struct": float(w.struct),
        "conflict": float(w.conflict),
    }
    fidelity = float(getattr(w, "fidelity", 0.0) or 0.0)
    if fidelity > 0:
        base["fidelity"] = fidelity
        return base
    # 旧配置：把 4 项按 0.7 缩放，给 fidelity 留 0.30
    scale = 0.7 / max(sum(base.values()), 1e-9)
    return {**{k: v * scale for k, v in base.items()}, "fidelity": 0.30}


def evaluate_confidence_batch(rules: list[RuleCandidate], cfg: Config) -> list[RuleCandidate]:
    return [evaluate_confidence(r, cfg) for r in rules]


def is_low_confidence(rule: RuleCandidate, cfg: Config) -> bool:
    return rule.combined_confidence < cfg.confidence.threshold_review


def filter_low_confidence(rules: list[RuleCandidate], cfg: Config) -> list[RuleCandidate]:
    return [r for r in rules if is_low_confidence(r, cfg)]


def compute_confidence_summary(rules: list[RuleCandidate]) -> dict:
    if not rules:
        return {
            "count": 0,
            "avg_combined": 0.0,
            "avg_self": 0.0,
            "struct_pass_rate": 0.0,
            "conflict_count": 0,
        }
    total = len(rules)
    return {
        "count": total,
        "avg_combined": round(sum(r.combined_confidence for r in rules) / total, 4),
        "avg_self": round(sum(r.self_confidence for r in rules) / total, 4),
        "struct_pass_rate": round(
            sum(1 for r in rules if r.struct_check_pass) / total, 4
        ),
        "conflict_count": sum(1 for r in rules if r.conflict_flag != "无"),
    }


# ---------------------------------------------------------------------------
# Gate 2 — multi-sample consistency
# ---------------------------------------------------------------------------

def _should_double_sample(rule: RuleCandidate, cfg: Config) -> bool:
    """Per PRD §5.2: only re-sample high-risk or red-line-keyword-hit candidates."""
    if not cfg.extraction.consistency_sampling:
        return False
    if rule.risk_level == "高":
        return True
    return any(kw in rule.source_excerpt for kw in cfg.extraction.redline_keywords)


async def apply_consistency(
    rules: list[RuleCandidate],
    cfg: Config,
    router: LLMRouter,
    *,
    resample_fn,
) -> list[RuleCandidate]:
    """Re-extract eligible rules at a second temperature and compare fingerprints.

    ``resample_fn`` is an injected coroutine ``(rule) -> RuleCandidate | None`` so
    this module stays decoupled from any specific pipeline / prompt. The caller
    (typically the orchestrator) supplies one bound to the right pipeline.

    The returned list mirrors the input order. ``rule.combined_confidence`` is
    *not* recomputed here — the caller should call :func:`evaluate_confidence_batch`
    afterwards if a fresh score is needed.
    """
    indices = [i for i, r in enumerate(rules) if _should_double_sample(r, cfg)]
    if not indices:
        return list(rules)

    sem = asyncio.Semaphore(cfg.concurrency.blocks)

    async def gated(i: int):
        async with sem:
            try:
                return i, await resample_fn(rules[i])
            except Exception:
                logger.exception("Consistency resample failed for rule %d", i)
                return i, None

    results = await asyncio.gather(*[gated(i) for i in indices])
    updated = list(rules)
    for i, alt in results:
        primary = updated[i]
        if alt is None:
            updated[i] = replace(primary, struct_failures=primary.struct_failures + ("consistency_resample_failed",))
            continue
        score = _consistency_score(primary, alt)
        # 把一致性结果存到 `notes` 末尾，主分数走综合公式；这里直接覆盖 combined_confidence
        # 让外层重新加权时能拿到一致性分。
        updated[i] = replace(
            primary,
            combined_confidence=round((primary.combined_confidence + score) / 2, 4),
        )
    return updated


def _consistency_score(a: RuleCandidate, b: RuleCandidate) -> float:
    """Lightweight three-component similarity in [0,1]."""
    a_fp = compute_fingerprint({
        "theme_key": a.theme_key, "subject": a.subject, "predicate": a.predicate,
        "threshold_type": a.threshold_type, "direction": a.direction,
    })
    b_fp = compute_fingerprint({
        "theme_key": b.theme_key, "subject": b.subject, "predicate": b.predicate,
        "threshold_type": b.threshold_type, "direction": b.direction,
    })
    fp_match = 1.0 if a_fp == b_fp else 0.0

    thr_match = 1.0 if _normalize_thresh(a.requirement) == _normalize_thresh(b.requirement) else 0.0
    dir_match = 1.0 if a.direction == b.direction else 0.0
    return 0.5 * fp_match + 0.3 * thr_match + 0.2 * dir_match


def _normalize_thresh(text: str) -> str:
    import re
    nums = re.findall(r"\d+(?:\.\d+)?%?", text)
    return "|".join(sorted(set(nums)))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))
