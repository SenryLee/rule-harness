from __future__ import annotations

from dataclasses import replace

from .config import Config
from .parsers import RuleCandidate


def evaluate_confidence(rule: RuleCandidate, cfg: Config) -> RuleCandidate:
    weights = cfg.confidence.weights
    self_score = max(0.0, min(1.0, rule.self_confidence))
    consistency_score = self_score
    struct_score = 1.0 if rule.struct_check_pass else 0.0
    conflict_score = 1.0 if rule.conflict_flag == "无" else 0.0

    combined = (
        weights.self_ * self_score
        + weights.consistency * consistency_score
        + weights.struct * struct_score
        + weights.conflict * conflict_score
    )
    combined = round(max(0.0, min(1.0, combined)), 4)

    return replace(rule, combined_confidence=combined)


def evaluate_confidence_batch(
    rules: list[RuleCandidate], cfg: Config
) -> list[RuleCandidate]:
    return [evaluate_confidence(r, cfg) for r in rules]


def is_low_confidence(rule: RuleCandidate, cfg: Config) -> bool:
    threshold = cfg.confidence.threshold_review
    return rule.combined_confidence < threshold


def filter_low_confidence(
    rules: list[RuleCandidate], cfg: Config
) -> list[RuleCandidate]:
    return [r for r in rules if is_low_confidence(r, cfg)]


def compute_confidence_summary(
    rules: list[RuleCandidate],
) -> dict:
    if not rules:
        return {
            "count": 0,
            "avg_combined": 0.0,
            "avg_self": 0.0,
            "struct_pass_rate": 0.0,
            "conflict_count": 0,
        }

    total = len(rules)
    avg_combined = sum(r.combined_confidence for r in rules) / total
    avg_self = sum(r.self_confidence for r in rules) / total
    struct_pass_count = sum(1 for r in rules if r.struct_check_pass)
    conflict_count = sum(1 for r in rules if r.conflict_flag != "无")

    return {
        "count": total,
        "avg_combined": round(avg_combined, 4),
        "avg_self": round(avg_self, 4),
        "struct_pass_rate": round(struct_pass_count / total, 4),
        "conflict_count": conflict_count,
    }
