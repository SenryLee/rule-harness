from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import replace

from .config import Config
from .harness import compute_fingerprint
from .parsers import RuleCandidate


def dedupe_with_priority(
    candidates: list[RuleCandidate], cfg: Config
) -> list[RuleCandidate]:
    groups: dict[str, list[RuleCandidate]] = defaultdict(list)
    for c in candidates:
        key = compute_fingerprint(_candidate_to_dict(c))
        groups[key].append(c)

    deduped: list[RuleCandidate] = []
    for fp, group in groups.items():
        sorted_group = sorted(group, key=lambda c: (c.priority, -c.self_confidence))
        primary = sorted_group[0]
        variants = sorted_group[1:]

        if variants:
            serialized = serialize_variants(variants)
            new_conflict_flag = _determine_conflict(primary, variants)
            primary = replace(
                primary,
                variant_versions=serialized,
                conflict_flag=new_conflict_flag,
                fingerprint=fp,
            )
        else:
            primary = replace(primary, fingerprint=fp)

        deduped.append(primary)

    return deduped


def _determine_conflict(
    primary: RuleCandidate, variants: list[RuleCandidate]
) -> str:
    if has_threshold_conflict(primary, variants):
        return "阈值冲突"
    if has_cross_source_diff(primary, variants):
        return "跨源冲突"
    return "无"


def has_threshold_conflict(
    primary: RuleCandidate, variants: list[RuleCandidate]
) -> bool:
    all_candidates = [primary] + list(variants)
    thresholds: set[tuple[str, str]] = set()
    for c in all_candidates:
        key = (c.threshold_type, _extract_numeric(c.requirement))
        thresholds.add(key)
    return len(thresholds) > 1


def _extract_numeric(text: str) -> str:
    import re

    nums = re.findall(r"\d+(?:\.\d+)?%?", text)
    return "|".join(nums) if nums else "no_number"


def has_cross_source_diff(
    primary: RuleCandidate, variants: list[RuleCandidate]
) -> bool:
    primary_source = primary.source_tag
    for v in variants:
        if v.source_tag != primary_source:
            return True
    return False


def serialize_variants(variants: list[RuleCandidate]) -> str:
    items = []
    for v in variants:
        items.append({
            "rule_id": getattr(v, "rule_id", ""),
            "risk_level": v.risk_level,
            "keywords": list(v.keywords),
            "check_item": v.check_item,
            "requirement": v.requirement,
            "notes": v.notes,
            "source_tag": v.source_tag,
            "source_filename": v.source_filename,
            "priority": v.priority,
            "self_confidence": v.self_confidence,
            "threshold_type": v.threshold_type,
            "direction": v.direction,
            "pipeline": v.pipeline,
        })
    return json.dumps(items, ensure_ascii=False)


def _candidate_to_dict(c: RuleCandidate) -> dict:
    return {
        "theme_key": c.theme_key,
        "subject": c.subject,
        "predicate": c.predicate,
        "threshold_type": c.threshold_type,
        "direction": c.direction,
    }


def build_rule_ids(candidates: list[RuleCandidate]) -> list[RuleCandidate]:
    from .harness import build_rule_id

    results: list[RuleCandidate] = []
    for c in candidates:
        rule_id = build_rule_id(
            _candidate_to_dict(c), list(c.contract_types)
        )
        fp = compute_fingerprint(_candidate_to_dict(c))
        results.append(replace(c, rule_id=rule_id, fingerprint=fp))
    return results
