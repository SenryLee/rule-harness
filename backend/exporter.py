from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from .merger import MergeDecision
from .parsers import RuleCandidate

_MAIN_CSV_HEADERS = [
    "规则项id", "是否启用", "风险程度", "关键词",
    "检查项", "审查要求", "审查说明",
]

_METADATA_CSV_HEADERS = [
    "规则项id", "规则类型", "适用合同类型", "法域",
    "来源文件名", "来源文件sha256", "来源页码或段落", "原文片段",
    "抽取管道", "模型", "模型自评置信度", "一致性置信度",
    "结构校验通过", "冲突标记", "综合置信度", "theme_key",
    "退让阶梯_首选", "退让阶梯_可接受", "退让阶梯_不可接受",
    "引用判例", "父规则id", "变体口径",
    "首次入库批次", "最近更新批次", "抽取时间戳", "版本号",
    "subject", "predicate", "threshold_type", "direction",
    "uncertainty_points",
]


def export_main_csv(
    rules: list[RuleCandidate], output_path: Path
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_MAIN_CSV_HEADERS)

        for rule in rules:
            keywords_str = ", ".join(rule.keywords) if rule.keywords else ""
            writer.writerow([
                getattr(rule, "rule_id", ""),
                "启用",
                rule.risk_level,
                keywords_str,
                rule.check_item,
                rule.requirement,
                rule.notes,
            ])


def export_metadata_csv(
    rules: list[RuleCandidate], output_path: Path
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat()

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_METADATA_CSV_HEADERS)

        for rule in rules:
            contract_types_str = ", ".join(rule.contract_types) if rule.contract_types else ""
            uncertainties_str = ", ".join(rule.uncertainty_points) if rule.uncertainty_points else ""

            writer.writerow([
                getattr(rule, "rule_id", ""),
                _rule_type_label(rule.rule_type),
                contract_types_str,
                _get_jurisdiction(rule),
                rule.source_filename,
                rule.source_sha256,
                rule.source_location,
                rule.source_excerpt[:500],
                rule.pipeline,
                rule.model,
                rule.self_confidence,
                "",
                int(rule.struct_check_pass),
                rule.conflict_flag,
                rule.combined_confidence,
                rule.theme_key,
                rule.ladder.get("preferred", "") if rule.ladder else "",
                rule.ladder.get("acceptable", "") if rule.ladder else "",
                rule.ladder.get("unacceptable", "") if rule.ladder else "",
                ", ".join(rule.cited_cases) if rule.cited_cases else "",
                "",
                getattr(rule, "variant_versions", ""),
                "",
                "",
                now,
                1,
                rule.subject,
                rule.predicate,
                rule.threshold_type,
                rule.direction,
                uncertainties_str,
            ])


def _rule_type_label(rule_type: str) -> str:
    return {"clause": "条款", "governance": "合规", "negative": "反向"}.get(
        rule_type, rule_type
    )


def _get_jurisdiction(rule: RuleCandidate) -> str:
    return "中国大陆"


def export_conflict_report(
    rules: list[RuleCandidate], batch_id: str, output_path: Path
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    conflicts = [r for r in rules if r.conflict_flag != "无"]
    threshold_conflicts = [r for r in conflicts if r.conflict_flag == "阈值冲突"]
    cross_source_conflicts = [r for r in conflicts if r.conflict_flag == "跨源冲突"]

    html_parts = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="UTF-8">',
        "<title>冲突报告</title>",
        "<style>",
        "body { font-family: -apple-system, 'Microsoft YaHei', sans-serif; "
        "margin: 20px; color: #333; }",
        "h1 { border-bottom: 2px solid #e74c3c; padding-bottom: 8px; }",
        ".summary { background: #f8f9fa; padding: 16px; border-radius: 6px; "
        "margin-bottom: 20px; }",
        ".summary-item { display: inline-block; margin-right: 24px; }",
        ".summary-value { font-size: 24px; font-weight: bold; color: #e74c3c; }",
        "table { width: 100%; border-collapse: collapse; margin-top: 12px; }",
        "th { background: #f1f3f5; padding: 10px; text-align: left; "
        "border-bottom: 2px solid #dee2e6; }",
        "td { padding: 10px; border-bottom: 1px solid #e9ecef; "
        "vertical-align: top; }",
        "tr:hover { background: #f8f9fa; }",
        ".tag { display: inline-block; padding: 2px 8px; border-radius: 3px; "
        "font-size: 12px; font-weight: bold; }",
        ".tag-conflict { background: #ffe3e3; color: #c92a2a; }",
        ".tag-warning { background: #fff3bf; color: #e67700; }",
        ".variant-card { background: #fff; border: 1px solid #dee2e6; "
        "padding: 8px; margin: 4px 0; border-radius: 4px; font-size: 13px; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>冲突报告</h1>",
        f"<p>批次: {escape(batch_id)} | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>",
        '<div class="summary">',
        f'<div class="summary-item">冲突总数: '
        f'<span class="summary-value">{len(conflicts)}</span></div>',
        f'<div class="summary-item">阈值冲突: '
        f'<span class="summary-value">{len(threshold_conflicts)}</span></div>',
        f'<div class="summary-item">跨源冲突: '
        f'<span class="summary-value">{len(cross_source_conflicts)}</span></div>',
        "</div>",
    ]

    if conflicts:
        html_parts.append("<h2>冲突详情</h2>")
        html_parts.append("<table>")
        html_parts.append(
            "<tr><th>指纹</th><th>主规则</th><th>冲突类型</th>"
            "<th>变体详情</th><th>来源文件</th></tr>"
        )

        for rule in conflicts:
            fp = getattr(rule, "fingerprint", "")
            variant_html = _render_variant_html(rule)
            source_link = _file_link(rule.source_filename)

            html_parts.append(
                f"<tr>"
                f"<td><code>{escape(fp)}</code></td>"
                f"<td>{escape(rule.check_item)}</td>"
                f"<td><span class='tag tag-conflict'>{escape(rule.conflict_flag)}</span></td>"
                f"<td>{variant_html}</td>"
                f"<td>{source_link}</td>"
                f"</tr>"
            )

        html_parts.append("</table>")
    else:
        html_parts.append("<p>本批次无冲突。</p>")

    html_parts.extend(["</body>", "</html>"])

    output_path.write_text("\n".join(html_parts), encoding="utf-8")


def _render_variant_html(rule: RuleCandidate) -> str:
    variant_data = getattr(rule, "variant_versions", "")
    if not variant_data:
        return "<em>无变体</em>"

    try:
        variants = json.loads(variant_data)
    except (json.JSONDecodeError, TypeError):
        return escape(str(variant_data))

    parts = []
    for v in variants:
        if isinstance(v, dict):
            parts.append(
                f'<div class="variant-card">'
                f"<strong>{escape(v.get('source_tag', ''))}</strong> "
                f"(P{v.get('priority', '?')}): "
                f"{escape(v.get('requirement', '')[:80])}"
                f"</div>"
            )
    return "\n".join(parts) if parts else "<em>无变体</em>"


def _file_link(filename: str) -> str:
    safe_name = escape(filename)
    return f'<span title="{safe_name}">{safe_name}</span>'


def export_change_set(
    decisions: list[MergeDecision], output_path: Path
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    headers = [
        "规则项id", "action", "旧风险程度", "新风险程度",
        "旧关键词", "新关键词", "旧检查项", "新检查项",
        "旧审查要求", "新审查要求", "来源文件", "冲突说明",
    ]

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for decision in decisions:
            new_rule = decision.new_rule or {}
            old_rule = decision.old_rule or {}

            old_risk = old_rule.get("risk_level", "") if old_rule else ""
            new_risk = new_rule.get("risk_level", "") if new_rule else ""
            old_kw = ", ".join(old_rule.get("keywords", [])) if old_rule else ""
            new_kw = ", ".join(new_rule.get("keywords", [])) if new_rule else ""
            old_check = old_rule.get("check_item", "") if old_rule else ""
            new_check = new_rule.get("check_item", "") if new_rule else ""
            old_req = old_rule.get("requirement", "") if old_rule else ""
            new_req = new_rule.get("requirement", "") if new_rule else ""
            source_file = new_rule.get("source_filename", "") if new_rule else ""
            conflict_note = decision.reason

            writer.writerow([
                decision.rule_id,
                decision.action,
                old_risk,
                new_risk,
                old_kw,
                new_kw,
                old_check,
                new_check,
                old_req,
                new_req,
                source_file,
                conflict_note,
            ])


def export_summary_html(
    rules: list[RuleCandidate],
    batch_id: str,
    token_usage: dict | None,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total = len(rules)
    high = sum(1 for r in rules if r.risk_level == "高")
    mid = sum(1 for r in rules if r.risk_level == "中")
    low = sum(1 for r in rules if r.risk_level == "低")
    low_conf = sum(1 for r in rules if r.combined_confidence < 0.7)
    conflict_count = sum(1 for r in rules if r.conflict_flag != "无")

    pipeline_counts: dict[str, int] = {}
    for r in rules:
        pipeline_counts[r.pipeline] = pipeline_counts.get(r.pipeline, 0) + 1

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>批次摘要 - {escape(batch_id)}</title>
<style>
body {{ font-family: -apple-system, 'Microsoft YaHei', sans-serif; margin: 20px; color: #333; }}
h1 {{ border-bottom: 2px solid #4a90d9; padding-bottom: 8px; }}
.cards {{ display: flex; flex-wrap: wrap; gap: 16px; margin: 20px 0; }}
.card {{ background: #f8f9fa; border-radius: 8px; padding: 16px; min-width: 140px; flex: 1; }}
.card-value {{ font-size: 28px; font-weight: bold; color: #4a90d9; }}
.card-label {{ font-size: 14px; color: #666; margin-top: 4px; }}
.card.high .card-value {{ color: #e74c3c; }}
.card.warn .card-value {{ color: #e67700; }}
.pipeline-row {{ display: flex; gap: 24px; margin: 8px 0; }}
</style>
</head>
<body>
<h1>批次摘要</h1>
<p>批次ID: {escape(batch_id)} | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
<div class="cards">
<div class="card"><div class="card-value">{total}</div><div class="card-label">总规则数</div></div>
<div class="card high"><div class="card-value">{high}</div><div class="card-label">高风险</div></div>
<div class="card"><div class="card-value">{mid}</div><div class="card-label">中风险</div></div>
<div class="card"><div class="card-value">{low}</div><div class="card-label">低风险</div></div>
<div class="card warn"><div class="card-value">{low_conf}</div><div class="card-label">需复核</div></div>
<div class="card high"><div class="card-value">{conflict_count}</div><div class="card-label">冲突数</div></div>
</div>
<h2>管道产出</h2>
<div class="pipeline-row">
{"".join(f'<div class="card"><div class="card-value">{cnt}</div><div class="card-label">{pipe}</div></div>' for pipe, cnt in sorted(pipeline_counts.items()))}
</div>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
