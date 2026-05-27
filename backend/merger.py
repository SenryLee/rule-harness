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

    old_dict = _coerce_record_to_dict(old)

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


def _coerce_record_to_dict(record) -> dict:
    """Convert a SQLite RuleRecord / metadata dataclass / sqlite3.Row to a dict.

    The legacy code assumed ``dict(record)`` would work for anything truthy.
    For frozen dataclasses (which is what ``storage.find_rule_by_fingerprint``
    actually returns) that raises ``TypeError`` and the merge silently degrades
    to "always new" — breaking the increment-merge contract entirely.
    """
    if isinstance(record, dict):
        return record
    if hasattr(record, "_asdict"):
        return record._asdict()  # sqlite3.Row
    try:
        from dataclasses import asdict, is_dataclass
        if is_dataclass(record):
            return asdict(record)
    except Exception:
        pass
    # Last resort: vars() on a plain object.
    if hasattr(record, "__dict__"):
        return dict(record.__dict__)
    return dict(record)


def rules_equivalent(a: dict, b: dict) -> bool:
    for field in _EQUIVALENT_FIELDS:
        val_a = _normalize_for_compare(a.get(field))
        val_b = _normalize_for_compare(b.get(field))
        if val_a != val_b:
            return False
    return True


_LIST_SPLIT_RX = None  # initialised lazily


def _normalize_for_compare(value: object) -> object:
    """Order-insensitive, format-tolerant normalisation for diff comparisons.

    Storage flattens list fields (``keywords``, ``contract_types`` etc.) into
    comma-separated strings; in-memory candidates keep them as ``list``. This
    helper coerces both to the same shape so a re-extracted rule round-trips
    as ``skip`` rather than ``new``.
    """
    import re as _re

    global _LIST_SPLIT_RX
    if _LIST_SPLIT_RX is None:
        _LIST_SPLIT_RX = _re.compile(r"[,，;；、]")

    if isinstance(value, (list, tuple)):
        return tuple(sorted(str(v).strip() for v in value if str(v).strip()))
    if isinstance(value, str):
        s = value.strip()
        # Fields like "保密, LPR, 30%" or "采购, 服务" — treat as a list when split.
        if _LIST_SPLIT_RX.search(s):
            parts = [p.strip() for p in _LIST_SPLIT_RX.split(s) if p.strip()]
            return tuple(sorted(parts))
        return s
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
        try:
            if action == "new":
                storage.insert_rule(decision.new_rule, batch_id)
            elif action == "update":
                storage.update_rule(decision.rule_id, decision.new_rule, batch_id)
            elif action == "add_variant":
                storage.add_variant(decision.rule_id, decision.new_rule)
            elif action == "conflict":
                # 冲突不动主库，只记 history
                pass
        except Exception:
            logger.exception("Failed to apply decision %s for rule %s",
                             action, decision.rule_id)

        storage.record_merge_history(
            batch_id=batch_id,
            rule_id=decision.rule_id,
            action=action,
            diff_payload=json.dumps(decision.diff, ensure_ascii=False)
            if decision.diff
            else None,
        )
