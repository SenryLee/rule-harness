"""v1.4 文件夹内多任务规则合并去重（手动触发）。

操作 API-ready 规则 dict（state.batch_rules / batch_payloads 里的格式），
不依赖 RuleCandidate dataclass——这样重启后从 SQLite 恢复的任务也能合并。

两级去重：
  1. 指纹级：fingerprint 完全相同 → 同一条规则，保最优；
  2. 结构级：theme_key+subject+predicate+threshold_type+direction 相同
     → 近重复（同一检查口径的不同表述），保最优，其余计入 variants。

"最优"判定：来源优先级小者 > 综合置信度高者 > 后抽取者。
"""
from __future__ import annotations

from typing import Any


def _better(a: dict, b: dict) -> dict:
    """返回 a/b 中更优的一条。"""
    pa = a.get("priority") or 5
    pb = b.get("priority") or 5
    if pa != pb:
        return a if pa < pb else b
    ca = a.get("combined_confidence") or a.get("confidence") or 0
    cb = b.get("combined_confidence") or b.get("confidence") or 0
    if ca != cb:
        return a if ca > cb else b
    return b  # 平手保后者（后抽取的）


def _struct_key(rule: dict) -> tuple | None:
    theme = (rule.get("theme_key") or "").strip()
    subject = (rule.get("subject") or "").strip()
    predicate = (rule.get("predicate") or "").strip()
    threshold = (rule.get("threshold_type") or "").strip()
    direction = (rule.get("direction") or "").strip()
    if not theme or not predicate:
        return None  # 结构信息不全的不参与结构级去重
    return (theme, subject, predicate, threshold, direction)


def merge_rules_across_batches(
    rules_by_batch: dict[str, list[dict]],
    main_only: bool = True,
) -> tuple[list[dict], dict[str, Any]]:
    """合并多任务规则。返回 (merged_rules, stats)。"""
    flat: list[dict] = []
    per_batch_in: dict[str, int] = {}
    for batch_id, rules in rules_by_batch.items():
        selected = [
            {**r, "_merge_batch_id": batch_id}
            for r in rules
            if not main_only or (r.get("output_target") or "main") == "main"
        ]
        per_batch_in[batch_id] = len(selected)
        flat.extend(selected)

    total_in = len(flat)

    # 1) 指纹级
    by_fp: dict[str, dict] = {}
    no_fp: list[dict] = []
    fp_dups = 0
    for rule in flat:
        fp = (rule.get("fingerprint") or "").strip()
        if not fp:
            no_fp.append(rule)
            continue
        if fp in by_fp:
            fp_dups += 1
            winner = _better(by_fp[fp], rule)
            winner = {**winner, "merge_dup_count": by_fp[fp].get("merge_dup_count", 1) + 1}
            by_fp[fp] = winner
        else:
            by_fp[fp] = {**rule, "merge_dup_count": 1}
    stage1 = list(by_fp.values()) + [{**r, "merge_dup_count": 1} for r in no_fp]

    # 2) 结构级
    by_struct: dict[tuple, dict] = {}
    passthrough: list[dict] = []
    struct_dups = 0
    for rule in stage1:
        key = _struct_key(rule)
        if key is None:
            passthrough.append(rule)
            continue
        if key in by_struct:
            struct_dups += 1
            existing = by_struct[key]
            winner = _better(existing, rule)
            loser = rule if winner is existing else existing
            variants = list(existing.get("merge_variants") or [])
            variants.append({
                "rule_id": loser.get("rule_id", ""),
                "batch_id": loser.get("_merge_batch_id", ""),
                "requirement": (loser.get("requirement") or "")[:120],
            })
            by_struct[key] = {
                **winner,
                "merge_variants": variants,
                "merge_dup_count": existing.get("merge_dup_count", 1) + rule.get("merge_dup_count", 1),
            }
        else:
            by_struct[key] = rule
    merged = list(by_struct.values()) + passthrough

    # 清理内部标记 → 输出字段
    out: list[dict] = []
    for rule in merged:
        item = dict(rule)
        item["merge_source_batch"] = item.pop("_merge_batch_id", "")
        out.append(item)
    out.sort(key=lambda r: (
        {"高": 0, "中": 1, "低": 2}.get(r.get("risk_level") or "中", 1),
        -(r.get("combined_confidence") or r.get("confidence") or 0),
    ))

    stats = {
        "batches": len(rules_by_batch),
        "total_in": total_in,
        "fingerprint_dups_removed": fp_dups,
        "struct_dups_removed": struct_dups,
        "total_out": len(out),
        "per_batch_in": per_batch_in,
    }
    return out, stats
