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
from .fidelity import is_low_severity
from .harness import compute_fingerprint
from .llm import LLMRouter
from .parsers import RuleCandidate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gate aggregation
# ---------------------------------------------------------------------------

def evaluate_confidence(rule: RuleCandidate, cfg: Config) -> RuleCandidate:
    """综合置信度 = 自评 + 一致性 + 结构 + 冲突 + 忠实度 + **语义忠实度**（v2.0 新增第六重门）。

    v2.0 改进：``consistency_score`` 不再直接等于 ``self_score``（根因 C 修复）。
    改为基于多门表现的衍生分数： ``(fidelity + semantic + struct) / 3``。
    这反映了"规则在多道校验门中的一致性表现"——通过了所有门的规则一致性高，
    任一门失败的规则一致性降低。零 LLM 成本，可审计。

    cfg.confidence.weights 现在含 6 项；为兼容旧 yaml（只配 4-5 项），未配置的
    ``fidelity`` 权重缺省取 0.25、``semantic`` 权重缺省取 0.15，并把现有项按比例
    缩放（详见 :func:`_resolve_weights`）。
    """
    weights = _resolve_weights(cfg)
    self_score = _clamp01(rule.self_confidence)
    struct_score = 1.0 if rule.struct_check_pass else 0.0
    conflict_score = 1.0 if rule.conflict_flag == "无" else 0.0
    fidelity_score = 1.0 if rule.fidelity_pass else 0.0
    # v2.0: 语义忠实度——通过则满分，未通过则按偏离率扣分
    semantic_score = 1.0 if rule.semantic_pass else _clamp01(1.0 - rule.semantic_deviation)
    # v2.0: 一致性分数改为多门衍生（根因 C 修复，不再等于 self_score）
    consistency_score = (fidelity_score + semantic_score + struct_score) / 3.0

    combined = (
        weights["self"] * self_score
        + weights["consistency"] * consistency_score
        + weights["struct"] * struct_score
        + weights["conflict"] * conflict_score
        + weights["fidelity"] * fidelity_score
        + weights["semantic"] * semantic_score
    )
    combined = _clamp01(combined)

    # v2.0 根因 G: 单数字失败强制降级——1 个数字 ground 不上时，
    # 强制 combined_confidence < threshold_review（0.7），确保触发人工复核。
    # ≥2 个失败已在 _apply_fidelity_gate 中被 discarded，此处只处理 1 个的情况。
    if is_low_severity(rule.fidelity_failures):
        combined = min(combined, 0.69)

    return replace(rule, combined_confidence=round(combined, 4))


def _resolve_weights(cfg: Config) -> dict[str, float]:
    """读出 6 项权重，对仍是 4-5 项的旧配置自动迁移。"""
    w = cfg.confidence.weights
    base = {
        "self": float(w.self_),
        "consistency": float(w.consistency),
        "struct": float(w.struct),
        "conflict": float(w.conflict),
    }
    fidelity = float(getattr(w, "fidelity", 0.0) or 0.0)
    semantic = float(getattr(w, "semantic", 0.0) or 0.0)

    if fidelity > 0 and semantic > 0:
        base["fidelity"] = fidelity
        base["semantic"] = semantic
        return base
    if fidelity > 0 and semantic <= 0:
        # 有 fidelity 无 semantic：从 fidelity 中拆出 semantic
        base["fidelity"] = fidelity * 0.625  # 0.25/0.40 比例
        base["semantic"] = fidelity * 0.375
        return base
    # 旧配置（4 项无 fidelity/semantic）：按 0.6 缩放，给 fidelity 0.25 + semantic 0.15
    scale = 0.6 / max(sum(base.values()), 1e-9)
    return {
        **{k: v * scale for k, v in base.items()},
        "fidelity": 0.25,
        "semantic": 0.15,
    }


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
    """Per PRD §5.2: only re-sample high-risk or red-line-keyword-hit candidates.

    v2.0: 即使 ``consistency_sampling=false``，若 ``consistency_sampling_high_risk_only=true``
    且 ``risk_level=高``，也触发双采样（根因 C 修复——高风险规则不再跳过一致性门）。
    """
    if cfg.extraction.consistency_sampling:
        return True  # 全局开启 → 所有规则都可双采样
    if cfg.extraction.consistency_sampling_high_risk_only and rule.risk_level == "高":
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
