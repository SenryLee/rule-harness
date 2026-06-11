"""v1.4 基于 API dict 的 CSV 导出（任务导出 / 合并导出 / 自定义导出共用）。

与 exporter.py（操作 RuleCandidate dataclass、批次结束时落盘）不同，
本模块操作 API-ready 规则 dict，可对重启后从 SQLite 恢复的任务即时生成 CSV。
"""
from __future__ import annotations

import csv
import io
from typing import Any, Callable


def _join(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value if v not in (None, ""))
    return str(value) if value is not None else ""


def _enabled_label(value: Any) -> str:
    if isinstance(value, str):
        return value or "启用"
    return "启用" if value in (True, None) else "停用"


def _bool_label(value: Any) -> str:
    if value is None:
        return ""
    return "是" if value else "否"


def _conf(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return ""


def _ladder(rule: dict, key: str) -> str:
    ladder = rule.get("ladder") or {}
    if isinstance(ladder, dict):
        return str(ladder.get(key, "") or rule.get(f"ladder_{key}", "") or "")
    return str(rule.get(f"ladder_{key}", "") or "")


# 字段注册表：key → (分组, 中文表头, 取值函数)
FIELD_REGISTRY: dict[str, tuple[str, str, Callable[[dict], str]]] = {
    # ── 基础（规则模板 7 列） ──
    "rule_id":        ("基础", "规则项id", lambda r: str(r.get("rule_id", ""))),
    "enabled":        ("基础", "是否启用", lambda r: _enabled_label(r.get("enabled"))),
    "risk_level":     ("基础", "风险程度", lambda r: str(r.get("risk_level", ""))),
    "keywords":       ("基础", "关键词", lambda r: _join(r.get("keywords"))),
    "check_item":     ("基础", "检查项", lambda r: str(r.get("check_item", ""))),
    "requirement":    ("基础", "审查要求", lambda r: str(r.get("requirement", ""))),
    "notes":          ("基础", "审查说明", lambda r: str(r.get("notes", ""))),
    # ── 深度分析 ──
    "assumption":           ("深度分析", "假定条件", lambda r: str(r.get("assumption", ""))),
    "behavior_mode":        ("深度分析", "行为模式", lambda r: str(r.get("behavior_mode", ""))),
    "consequence":          ("深度分析", "法律后果", lambda r: str(r.get("consequence", ""))),
    "exception_conditions": ("深度分析", "例外情形", lambda r: str(r.get("exception_conditions", ""))),
    "review_action":        ("深度分析", "审查动作", lambda r: str(r.get("review_action", ""))),
    "transformation_note":  ("深度分析", "转化说明", lambda r: str(r.get("transformation_note", ""))),
    "uncertainty_points":   ("深度分析", "不确定点", lambda r: _join(r.get("uncertainty_points"))),
    # ── 结构画像 ──
    "rule_type":      ("结构画像", "规则类型", lambda r: str(r.get("rule_type", ""))),
    "theme_key":      ("结构画像", "主题键", lambda r: str(r.get("theme_key", ""))),
    "subject":        ("结构画像", "义务主体", lambda r: str(r.get("subject", ""))),
    "predicate":      ("结构画像", "谓词", lambda r: str(r.get("predicate", ""))),
    "threshold_type": ("结构画像", "阈值类型", lambda r: str(r.get("threshold_type", ""))),
    "direction":      ("结构画像", "方向", lambda r: str(r.get("direction", ""))),
    # ── 原文溯源 ──
    "source_file":     ("原文溯源", "来源文件", lambda r: str(r.get("source_file") or r.get("source_filename", ""))),
    "source_tag":      ("原文溯源", "来源类别", lambda r: str(r.get("source_tag", ""))),
    "source_location": ("原文溯源", "段落定位", lambda r: str(r.get("source_location", ""))),
    "source_excerpt":  ("原文溯源", "原文摘录", lambda r: str(r.get("source_excerpt", ""))),
    "pipeline":        ("原文溯源", "抽取管道", lambda r: str(r.get("pipeline", ""))),
    "model":           ("原文溯源", "抽取模型", lambda r: str(r.get("model", ""))),
    # ── 质量与置信 ──
    "self_confidence":     ("质量与置信", "自评置信度", lambda r: _conf(r.get("self_confidence"))),
    "combined_confidence": ("质量与置信", "综合置信度", lambda r: _conf(r.get("combined_confidence") or r.get("confidence"))),
    "struct_check_pass":   ("质量与置信", "结构校验通过", lambda r: _bool_label(r.get("struct_check_pass"))),
    "fidelity_pass":       ("质量与置信", "数值忠实通过", lambda r: _bool_label(r.get("fidelity_pass"))),
    "fidelity_failures":   ("质量与置信", "忠实度问题", lambda r: _join(r.get("fidelity_failures"))),
    "voice_match":         ("质量与置信", "语态一致", lambda r: _bool_label(r.get("voice_match"))),
    "conflict_flag":       ("质量与置信", "冲突标记", lambda r: str(r.get("conflict_flag", ""))),
    # ── 适用范围 ──
    "contract_types": ("适用范围", "适用合同类型", lambda r: _join(r.get("contract_types"))),
    "jurisdiction":   ("适用范围", "法域", lambda r: str(r.get("jurisdiction", ""))),
    "task_mode":      ("适用范围", "任务模式", lambda r: str(r.get("task_mode", ""))),
    "scope_match":    ("适用范围", "范围判定", lambda r: str(r.get("scope_match", ""))),
    "scope_reason":   ("适用范围", "范围判定理由", lambda r: str(r.get("scope_reason", ""))),
    "output_target":  ("适用范围", "输出分桶", lambda r: str(r.get("output_target", "main"))),
    # ── 谈判阶梯 ──
    "ladder_preferred":    ("谈判阶梯", "优选条件", lambda r: _ladder(r, "preferred")),
    "ladder_acceptable":   ("谈判阶梯", "可接受条件", lambda r: _ladder(r, "acceptable")),
    "ladder_unacceptable": ("谈判阶梯", "不可接受条件", lambda r: _ladder(r, "unacceptable")),
}

# 预制方案
TEMPLATE_COLUMNS = [
    "rule_id", "enabled", "risk_level", "keywords",
    "check_item", "requirement", "notes",
]
LOCATED_COLUMNS = TEMPLATE_COLUMNS + [
    "source_file", "source_tag", "source_location", "source_excerpt", "pipeline",
]


def field_catalog() -> list[dict]:
    """供前端渲染勾选面板：[{key, group, label}]，注册表顺序即展示顺序。"""
    return [
        {"key": key, "group": group, "label": label}
        for key, (group, label, _) in FIELD_REGISTRY.items()
    ]


def rules_to_csv(rules: list[dict], columns: list[str]) -> str:
    """按列 key 列表渲染 CSV 文本（utf-8-sig 由调用方编码时加 BOM）。"""
    valid = [c for c in columns if c in FIELD_REGISTRY]
    if not valid:
        valid = list(TEMPLATE_COLUMNS)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([FIELD_REGISTRY[c][1] for c in valid])
    for rule in rules:
        writer.writerow([FIELD_REGISTRY[c][2](rule) for c in valid])
    return buf.getvalue()
