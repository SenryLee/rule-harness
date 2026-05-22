from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal

from .harness import compute_fingerprint
from .parsers import RuleCandidate

logger = logging.getLogger(__name__)

Action = Literal["new", "update", "skip", "add_variant", "conflict"]

_EQUIVALENT_FIELDS = ("risk_level", "keywords", "check_item", "requirement", "notes")


@dataclass(frozen=True)
class MergeDecision:
    rule_id: str
    action: Action
    new_rule: dict
    old_rule: dict | None
    diff: dict | None
    reason: str


def _encode_rule_for_merge(candidate: RuleCandidate) -> dict:
    return {
        "rule_id": candidate.rule_id,
        "fingerprint": candidate.fingerprint,
        "risk_level": candidate.risk_level,
        "keywords": list(candidate.keywords),
        "check_item": candidate.check_item,
        "requirement": candidate.requirement,
        "notes": candidate.notes,
        "rule_type": candidate.rule_type,
        "theme_key": candidate.theme_key,
        "subject": candidate.subject,
        "predicate": candidate.predicate,
        "threshold_type": candidate.threshold_type,
        "direction": candidate.direction,
        "source_filename": candidate.source_filename,
        "source_sha256": candidate.source_sha256,
        "source_tag": candidate.source_tag,
        "source_location": candidate.source_location,
        "source_excerpt": candidate.source_excerpt,
        "priority": candidate.priority,
        "contract_types": list(candidate.contract_types),
        "pipeline": candidate.pipeline,
        "model": candidate.model,
        "self_confidence": candidate.self_confidence,
        "combined_confidence": candidate.combined_confidence,
        "struct_check_pass": candidate.struct_check_pass,
        "struct_failures": list(candidate.struct_failures),
        "conflict_flag": candidate.conflict_flag,
        "variant_versions": candidate.variant_versions,
        "ladder": candidate.ladder,
        "cited_cases": list(candidate.cited_cases) if candidate.cited_cases else None,
        "uncertainty_points": list(candidate.uncertainty_points),
    }


def merge_rule(new: RuleCandidate, batch_id: str, storage=None) -> MergeDecision:
    new_dict = _encode_rule_for_merge(new)
    fp = new_dict.get("fingerprint", "") or compute_fingerprint(new_dict)

    old = None
    if storage is not None:
        old = storage.find_rule_by_fingerprint(fp)

    if old is None:
        rule_id = new_dict.get("rule_id", "")
        return MergeDecision(
            rule_id=rule_id,
            action="new",
            new_rule=new_dict,
            old_rule=None,
            diff=None,
            reason="new fingerprint",
        )

    old_dict = old if isinstance(old, dict) else dict(old)

    if rules_equivalent(new_dict, old_dict):
        return MergeDecision(
            rule_id=old_dict.get("rule_id", ""),
            action="skip",
            new_rule=new_dict,
            old_rule=old_dict,
            diff=None,
            reason="identical content",
        )

    new_priority = new_dict.get("priority", 5)
    old_priority = old_dict.get("priority", 5)

    if new_priority < old_priority:
        diff = build_diff(old_dict, new_dict)
        return MergeDecision(
            rule_id=old_dict.get("rule_id", ""),
            action="update",
            new_rule=new_dict,
            old_rule=old_dict,
            diff=diff,
            reason=f"higher priority: {new_priority} < {old_priority}",
        )
    elif new_priority > old_priority:
        return MergeDecision(
            rule_id=old_dict.get("rule_id", ""),
            action="add_variant",
            new_rule=new_dict,
            old_rule=old_dict,
            diff=None,
            reason=f"lower priority: {new_priority} > {old_priority}",
        )
    else:
        diff = build_diff(old_dict, new_dict)
        return MergeDecision(
            rule_id=old_dict.get("rule_id", ""),
            action="conflict",
            new_rule=new_dict,
            old_rule=old_dict,
            diff=diff,
            reason="same priority, content differs",
        )


def rules_equivalent(a: dict, b: dict) -> bool:
    for field in _EQUIVALENT_FIELDS:
        val_a = _normalize_for_compare(a.get(field))
        val_b = _normalize_for_compare(b.get(field))
        if val_a != val_b:
            return False
    return True


def _normalize_for_compare(value: object) -> object:
    if isinstance(value, (list, tuple)):
        return tuple(sorted(str(v).strip() for v in value))
    if isinstance(value, str):
        return value.strip()
    return value


def build_diff(old: dict, new: dict) -> dict:
    diff: dict = {}
    comparable_fields = [
        "risk_level", "keywords", "check_item", "requirement", "notes",
        "rule_type", "theme_key", "subject", "predicate", "threshold_type",
        "direction", "priority", "self_confidence",
    ]
    for field in comparable_fields:
        old_val = _normalize_for_compare(old.get(field))
        new_val = _normalize_for_compare(new.get(field))
        if old_val != new_val:
            diff[field] = {"old": old.get(field), "new": new.get(field)}
    return diff


def apply_merge_batch(
    decisions: list[MergeDecision], batch_id: str, storage=None
) -> dict:
    stats = {
        "batch_id": batch_id,
        "total": len(decisions),
        "new": 0,
        "update": 0,
        "skip": 0,
        "add_variant": 0,
        "conflict": 0,
        "errors": 0,
    }

    for decision in decisions:
        stats[decision.action] = stats.get(decision.action, 0) + 1

    if storage is not None:
        try:
            _persist_decisions(decisions, batch_id, storage)
        except Exception:
            logger.exception("Failed to persist merge batch %s", batch_id)
            stats["errors"] = len(decisions)

    return stats


def _persist_decisions(
    decisions: list[MergeDecision], batch_id: str, storage
) -> None:
    for decision in decisions:
        action = decision.action
        if action == "new":
            storage.insert_rule(decision.new_rule, batch_id)
        elif action == "update":
            storage.update_rule(decision.rule_id, decision.new_rule)
        elif action == "add_variant":
            storage.add_variant(decision.rule_id, decision.new_rule)
        elif action == "conflict":
            pass

        storage.record_merge_history(
            batch_id=batch_id,
            rule_id=decision.rule_id,
            action=action,
            diff_payload=json.dumps(decision.diff, ensure_ascii=False)
            if decision.diff
            else None,
        )
