"""Skill Builder — assembles extracted rules into a downloadable Claude skill ZIP.

Takes the output of a completed batch (list of rule dicts) and packages them
into the 法务AI平台 skill directory format:

    <domain>审查与起草/
    ├── SKILL.md
    ├── references/
    │   ├── 通用要点与纪律.md
    │   ├── 任务路由（审查与起草识别）.md
    │   ├── 审查规则-<立场A>立场.md
    │   ├── 审查规则-<立场B>立场.md
    │   ├── 起草要点与范例.md
    │   ├── 术语表.md
    │   └── 规则登记表（CSV字段）.md
    └── 导出/
        └── rules.csv

Public API:
    build_skill()           — build the skill directory and return path
    build_skill_zip()       — build + zip, return zip path
    enhance_skill_with_llm() — LLM-enhanced version with better descriptions
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config, PROJECT_ROOT

logger = logging.getLogger(__name__)

_SKILL_OUTPUT_DIR = PROJECT_ROOT / "data" / "skills"

# Six-dimension prefix mapping
_DIMENSION_PREFIXES: dict[str, tuple[str, str]] = {
    "SU": ("主体资格", "SU"),
    "PA": ("付款条件", "PA"),
    "BR": ("违约责任", "BR"),
    "IP": ("知识产权", "IP"),
    "CF": ("保密条款", "CF"),
    "DR": ("争议解决", "DR"),
}

# Theme key → dimension mapping
_THEME_TO_DIMENSION: dict[str, str] = {
    "主体": "SU", "资格": "SU", "资质": "SU", "签约": "SU",
    "付款": "PA", "价款": "PA", "费用": "PA", "结算": "PA", "支付": "PA",
    "违约": "BR", "赔偿": "BR", "损失": "BR", "罚则": "BR", "责任": "BR",
    "知识产权": "IP", "著作": "IP", "专利": "IP", "商标": "IP", "技术": "IP",
    "保密": "CF", "机密": "CF", "商业秘密": "CF",
    "争议": "DR", "仲裁": "DR", "诉讼": "DR", "管辖": "DR", "适用法律": "DR",
}


@dataclass
class SkillConfig:
    """Configuration for skill generation."""
    domain_name: str                     # e.g. "采购合同"
    party_perspectives: list[str]        # e.g. ["买方", "卖方"]
    include_drafting: bool = True
    llm_enhance: bool = False            # use LLM to polish descriptions


@dataclass
class BuiltSkill:
    """Result of skill building."""
    skill_id: str
    domain_name: str
    folder_name: str
    output_dir: Path
    zip_path: Path | None
    file_count: int
    rule_count: int
    dimension_stats: dict[str, int]


# ── Rule classification ─────────────────────────────────────────────

def _classify_dimension(rule: dict) -> str:
    """Assign a rule to one of the six dimensions."""
    # Try theme_key first
    theme = rule.get("theme_key", "")
    for keyword, dim in _THEME_TO_DIMENSION.items():
        if keyword in theme:
            return dim

    # Try check_item + requirement keywords
    text = f"{rule.get('check_item', '')} {rule.get('requirement', '')} {rule.get('notes', '')}"
    for keyword, dim in _THEME_TO_DIMENSION.items():
        if keyword in text:
            return dim

    # Default to BR (违约责任) as catch-all
    return "BR"


def _assign_rule_id(dimension: str, index: int, existing_id: str | None = None) -> str:
    """Generate a rule ID or keep existing one."""
    if existing_id and re.match(r'^[A-Z]{2,4}-[A-Z]{2,4}-\d{3,}$', existing_id):
        return existing_id
    return f"{dimension}-GEN-{index:03d}"


def _group_rules_by_dimension(rules: list[dict]) -> dict[str, list[dict]]:
    """Group rules into six dimensions."""
    groups: dict[str, list[dict]] = {dim: [] for dim in _DIMENSION_PREFIXES}
    for rule in rules:
        # Skip non-main rules
        target = rule.get("output_target", "main")
        if target not in ("main", "negotiation"):
            continue
        dim = _classify_dimension(rule)
        groups[dim].append(rule)
    return groups


def _group_rules_by_party(
    rules: list[dict],
    perspectives: list[str],
) -> dict[str, list[dict]]:
    """Group rules by party perspective. Rules not matching any go to '通用'."""
    groups: dict[str, list[dict]] = {p: [] for p in perspectives}
    groups["通用"] = []

    for rule in rules:
        direction = rule.get("direction", "")
        subject = rule.get("subject", "")
        our_party = rule.get("our_party", "")
        matched = False

        for perspective in perspectives:
            if perspective in direction or perspective in subject or perspective == our_party:
                groups[perspective].append(rule)
                matched = True
                break

        if not matched:
            groups["通用"].append(rule)

    return groups


# ── File generators ──────────────────────────────────────────────────

def _generate_skill_md(cfg: SkillConfig, dimension_stats: dict[str, int]) -> str:
    folder = f"{cfg.domain_name}审查与起草"
    perspectives = " / ".join(cfg.party_perspectives) if cfg.party_perspectives else "通用"
    total = sum(dimension_stats.values())

    perspective_refs = "\n".join(
        f"- 站在{p}审查：读 `/skills/{folder}/references/审查规则-{p}立场.md`"
        for p in cfg.party_perspectives
    )

    return f"""---
name: {folder}
description: >-
  适用于{cfg.domain_name}的审查与起草，覆盖{perspectives}立场。
  共 {total} 条审查规则，涵盖主体资格、付款条件、违约责任、知识产权、保密条款、争议解决六维度。
  触发短语：这份{cfg.domain_name}能不能签、帮我看{cfg.domain_name}风险、起草一份{cfg.domain_name}、
  对照红线检查这份{cfg.domain_name}。
---

# {cfg.domain_name}审查与起草

## 适用范围

适用：{cfg.domain_name}的审查、起草、对照红线把关，覆盖{perspectives}立场。
不适用：公司章程/制度文件/诉讼文书/律师函；只需单条条款润色或单术语解释。

## 任务目标

站在指定立场，识别{cfg.domain_name}中违反法律、易引发争议、表述不清或难执行的内容并给出可执行修改方向；或按规则起草一份正式{cfg.domain_name}文本。

## 处理步骤

1. 先判任务是审查还是起草、再判场景（哪一立场/子类）。
2. 审查：只加载当前场景对应的审查规则文件；起草：加载起草要点文件。
3. 六维度（主体/付款/违约/知产/保密/争议）自检覆盖；缺失事实写 `______`。
4. 引用规则末尾括注 `【规则项id, 风险程度】`。

> 最终输出的字段与排版由平台提示词统一规定，本 skill 只规定必须覆盖的实质内容。

## 重点审查事项

{"".join(f"- {label}（{_DIMENSION_PREFIXES[dim][0]}）：{count} 条规则{chr(10)}" for dim, (label, _) in _DIMENSION_PREFIXES.items() if (count := dimension_stats.get(dim, 0)) > 0)}

## 参考资料调用说明

- 判审查/起草与场景：先读 `/skills/{folder}/references/任务路由（审查与起草识别）.md`
- 六维度兜底与实质要求：读 `/skills/{folder}/references/通用要点与纪律.md`
{perspective_refs}
{f"- 起草{cfg.domain_name}：读 `/skills/{folder}/references/起草要点与范例.md`" if cfg.include_drafting else ""}
- 需要术语口径：读 `/skills/{folder}/references/术语表.md`
- 追溯规则出处：读 `/skills/{folder}/references/规则登记表（CSV字段）.md`（日常不加载）

除非当前场景需要，不要一次性读取全部文件。

## 注意事项

- 不对合法、合理、表述清楚的内容强行提意见；不脱离文本泛讲法律知识。
- 合同类型/立场不明时，先按通用规则输出，把识别假设写入"待确认事项"。
- 无法判断是否违法时提示需人工复核，不作绝对判断。
"""


def _generate_registry_md(
    grouped: dict[str, list[dict]],
    cfg: SkillConfig,
) -> str:
    """Generate the 规则登记表（CSV字段）.md with all rules in seven-column format."""
    lines = [
        f"# {cfg.domain_name}规则登记表（CSV 七字段对齐）\n",
        "> 本表是规则**单一事实源**，按六维度分章。",
        "> 与法天使 CSV 模板七字段一一对应。\n",
    ]

    dim_index = 0
    for dim, (label, prefix) in _DIMENSION_PREFIXES.items():
        dim_index += 1
        rules = grouped.get(dim, [])
        cn_label = "一二三四五六"[dim_index - 1] if dim_index <= 6 else str(dim_index)
        lines.append(f"\n## {cn_label}、{label}（{prefix}）\n")
        lines.append("| 规则项id | 是否启用 | 风险程度 | 关键词 | 检查项 | 审查要求 | 审查说明 |")
        lines.append("|---|---|---|---|---|---|---|")

        for idx, rule in enumerate(rules, 1):
            rule_id = _assign_rule_id(dim, idx, rule.get("rule_id"))
            rule["_skill_rule_id"] = rule_id
            enabled = "启用" if rule.get("enabled", True) else "停用"
            risk = rule.get("risk_level", "中")
            keywords = "、".join(rule.get("keywords", [])[:8])
            check = _escape_md_cell(rule.get("check_item", ""))
            req = _escape_md_cell(rule.get("requirement", ""))
            notes = _escape_md_cell(rule.get("notes", ""))
            lines.append(f"| {rule_id} | {enabled} | {risk} | {keywords} | {check} | {req} | {notes} |")

        if not rules:
            lines.append(f"| {prefix}-GEN-001 | 启用 | 中 | ______ | ______ | ______ | ______ |")

    return "\n".join(lines) + "\n"


def _generate_review_rules_md(
    perspective: str,
    rules: list[dict],
    cfg: SkillConfig,
    grouped_by_dim: dict[str, list[dict]],
) -> str:
    """Generate a single 审查规则-XX立场.md file."""
    lines = [
        f"# {cfg.domain_name}审查规则 · {perspective}立场\n",
        f"本文件只放**{perspective}立场**的审查规则。",
        "每条末尾括注 `【规则项id, 风险程度】`；按高、中、低排序。\n",
    ]

    # Group this perspective's rules by dimension
    dim_rules: dict[str, list[dict]] = {dim: [] for dim in _DIMENSION_PREFIXES}
    for rule in rules:
        dim = _classify_dimension(rule)
        dim_rules[dim].append(rule)

    # Also include "通用" rules if this is a specific perspective
    for dim in _DIMENSION_PREFIXES:
        # Sort by risk: 高 > 中 > 低
        risk_order = {"高": 0, "中": 1, "低": 2}
        dim_rules[dim].sort(key=lambda r: risk_order.get(r.get("risk_level", "中"), 1))

    dim_index = 0
    for dim, (label, prefix) in _DIMENSION_PREFIXES.items():
        drules = dim_rules.get(dim, [])
        if not drules:
            continue
        dim_index += 1
        cn_label = "一二三四五六"[dim_index - 1] if dim_index <= 6 else str(dim_index)
        lines.append(f"\n## {cn_label}、{label}（{prefix}）\n")

        for rule in drules:
            rule_id = rule.get("_skill_rule_id", rule.get("rule_id", ""))
            risk = rule.get("risk_level", "中")
            check = rule.get("check_item", "______")
            req = rule.get("requirement", "______")
            notes = rule.get("notes", "")
            keywords = "、".join(rule.get("keywords", [])[:5])

            lines.append(f"- {check} 【{rule_id}, {risk}】")
            lines.append(f"  - 触发：出现「{keywords}」相关内容时触发")
            lines.append(f"  - 红线：{req}")
            if notes:
                lines.append(f"  - 修改方向：{notes[:200]}")
            lines.append("")

    return "\n".join(lines) + "\n"


def _generate_common_md(cfg: SkillConfig) -> str:
    return f"""# {cfg.domain_name}通用要点与纪律

## 六维度兜底自检

审查完成前必须逐一确认以下六个维度都已覆盖，任一缺失视为未完成：

1. **主体资格（SU）**：签约主体是否适格、资质是否齐备。
2. **付款条件（PA）**：付款节点、比例、币种、发票、逾期利息。
3. **违约责任（BR）**：违约金上限、解除条件、赔偿范围。
4. **知识产权（IP）**：权属归属、许可范围、侵权担保。
5. **保密条款（CF）**：保密范围、期限、违约后果。
6. **争议解决（DR）**：管辖/仲裁、适用法律、送达地址。

## 实质内容要求

- 每条审查意见须给出：**触发事实 / 红线 / 修改方向**。
- 每个核心条款须覆盖：**主体·条件·动作·期限·后果**五层。
- 缺失事实写 `______`，不写"请填写"。
- 引用规则末尾括注 `【规则项id, 风险程度】`。

## 输出格式声明

最终输出的字段、排版、顺序由平台提示词统一规定，本 skill 不重复定义输出格式。
"""


def _generate_router_md(cfg: SkillConfig) -> str:
    folder = f"{cfg.domain_name}审查与起草"
    perspective_rules = "\n".join(
        f"  - 关键词含「{p}」时加载 `/skills/{folder}/references/审查规则-{p}立场.md`"
        for p in cfg.party_perspectives
    )
    return f"""# {cfg.domain_name}任务路由（审查与起草识别）

## 第一步：判断任务类型

- 用户给了**已有合同文本**要求审查/检查/把关 → **审查模式**
- 用户要求起草/拟定/出一份合同 → **起草模式**
- 不明确时默认**审查模式**

## 第二步：判断场景（审查模式）

根据合同文本中的关键词判断立场：

{perspective_rules}
  - 无法判断 → 按通用立场处理，在结果中注明"立场待确认"

## 第三步：加载对应文件

- 审查模式：加载对应立场的审查规则文件 + 通用要点
- 起草模式：加载起草要点与范例文件 + 通用要点
"""


def _generate_drafting_md(cfg: SkillConfig) -> str:
    return f"""# {cfg.domain_name}起草要点与范例

## 必出条款

以下条款在起草{cfg.domain_name}时**必须包含**：

- [必出] 合同主体条款：主体______、资质______
- [必出] 标的/范围条款：标的______、数量______、质量标准______
- [必出] 价款/付款条款：金额______、付款方式______、付款节点______
- [必出] 履行期限与地点：期限______、地点______
- [必出] 违约责任条款：违约情形______、违约金______、赔偿上限______
- [必出] 争议解决条款：仲裁/诉讼______、管辖______
- [可选] 知识产权条款
- [可选] 保密条款
- [可选] 不可抗力条款

## 每个条款的五层结构

起草时每个核心条款都应覆盖：

1. **主体**：谁
2. **条件**：在什么条件下
3. **动作**：做什么
4. **期限**：什么时间完成
5. **后果**：不做怎么办
"""


def _generate_glossary_md(cfg: SkillConfig, rules: list[dict]) -> str:
    """Extract unique terms from rules to build a glossary."""
    terms: dict[str, str] = {}
    for rule in rules:
        for kw in rule.get("keywords", []):
            if kw and len(kw) >= 2 and kw not in terms:
                terms[kw] = rule.get("check_item", "")
            if len(terms) >= 30:
                break

    lines = [f"# {cfg.domain_name}术语表\n"]
    lines.append("> 仅收录本领域专有术语；一般法律术语不重复收录。\n")

    for term, context in sorted(terms.items(), key=lambda x: x[0]):
        lines.append(f"- **{term}**：与「{context[:50]}」相关的专业术语。")

    if not terms:
        lines.append("（待补充）")

    return "\n".join(lines) + "\n"


def _generate_rules_csv(grouped: dict[str, list[dict]]) -> str:
    """Export rules as UTF-8-BOM CSV in the 法天使 seven-column format."""
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["规则项id", "是否启用", "风险程度", "关键词", "检查项", "审查要求", "审查说明"])

    for dim in _DIMENSION_PREFIXES:
        for idx, rule in enumerate(grouped.get(dim, []), 1):
            rule_id = rule.get("_skill_rule_id", _assign_rule_id(dim, idx, rule.get("rule_id")))
            enabled = "启用" if rule.get("enabled", True) else "停用"
            risk = rule.get("risk_level", "中")
            keywords = "、".join(rule.get("keywords", [])[:8])
            check = rule.get("check_item", "")
            req = rule.get("requirement", "")
            notes = rule.get("notes", "")
            writer.writerow([rule_id, enabled, risk, keywords, check, req, notes])

    return output.getvalue()


# ── Helpers ──────────────────────────────────────────────────────────

def _escape_md_cell(text: str) -> str:
    """Escape pipe characters in markdown table cells."""
    return text.replace("|", "\\|").replace("\n", " ").strip()[:300]


# ── LLM Enhancement ─────────────────────────────────────────────────

_SKILL_ENHANCE_SYSTEM = """你是一个法律AI skill优化专家。根据规则列表，为这个合同审查skill生成更精准的内容。
返回 JSON：
{
  "key_risks": ["3-5条最核心的高风险审查要点，每条20字以内"],
  "glossary_terms": [{"term": "术语", "definition": "定义，50字以内"}],
  "description_enhanced": "优化后的skill description，100字以内"
}"""


async def enhance_skill_with_llm(
    cfg: SkillConfig,
    rules: list[dict],
    router: Any,  # LLMRouter
) -> dict:
    """Use LLM to generate better descriptions and glossary."""
    sample_rules = rules[:30]
    rules_text = "\n".join(
        f"- [{r.get('risk_level','中')}] {r.get('check_item','')} → {r.get('requirement','')}"
        for r in sample_rules
    )
    user_msg = f"合同领域: {cfg.domain_name}\n立场: {', '.join(cfg.party_perspectives)}\n\n规则样本:\n{rules_text}"

    try:
        return await router.chat_json(
            system=_SKILL_ENHANCE_SYSTEM,
            user=user_msg,
            temperature=0.3,
        )
    except Exception as exc:
        logger.warning("LLM skill enhancement failed: %s", exc)
        return {}


# ── Main build functions ─────────────────────────────────────────────

def build_skill(
    rules: list[dict],
    cfg: SkillConfig,
    skill_id: str,
    output_root: Path | None = None,
) -> BuiltSkill:
    """Build the complete skill directory from extracted rules."""
    root = output_root or _SKILL_OUTPUT_DIR
    folder_name = f"{cfg.domain_name}审查与起草"
    skill_dir = root / skill_id / folder_name
    refs_dir = skill_dir / "references"
    export_dir = skill_dir / "导出"

    # Clean and recreate
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    refs_dir.mkdir(parents=True, exist_ok=True)
    export_dir.mkdir(parents=True, exist_ok=True)

    # Filter to main/negotiation rules only
    active_rules = [
        r for r in rules
        if r.get("output_target", "main") in ("main", "negotiation")
    ]

    # Group by dimension
    grouped = _group_rules_by_dimension(active_rules)

    # Assign rule IDs
    for dim, dim_rules in grouped.items():
        for idx, rule in enumerate(dim_rules, 1):
            rule["_skill_rule_id"] = _assign_rule_id(dim, idx, rule.get("rule_id"))

    dimension_stats = {dim: len(rules_list) for dim, rules_list in grouped.items()}

    # Generate SKILL.md
    (skill_dir / "SKILL.md").write_text(
        _generate_skill_md(cfg, dimension_stats), encoding="utf-8",
    )

    # Generate references
    (refs_dir / "通用要点与纪律.md").write_text(
        _generate_common_md(cfg), encoding="utf-8",
    )
    (refs_dir / "任务路由（审查与起草识别）.md").write_text(
        _generate_router_md(cfg), encoding="utf-8",
    )
    (refs_dir / "规则登记表（CSV字段）.md").write_text(
        _generate_registry_md(grouped, cfg), encoding="utf-8",
    )
    (refs_dir / "术语表.md").write_text(
        _generate_glossary_md(cfg, active_rules), encoding="utf-8",
    )

    # Generate per-perspective review rule files
    party_groups = _group_rules_by_party(active_rules, cfg.party_perspectives)
    for perspective in cfg.party_perspectives:
        perspective_rules = party_groups.get(perspective, [])
        # Also include generic rules
        perspective_rules = perspective_rules + party_groups.get("通用", [])
        (refs_dir / f"审查规则-{perspective}立场.md").write_text(
            _generate_review_rules_md(perspective, perspective_rules, cfg, grouped),
            encoding="utf-8",
        )

    # Generate drafting file
    if cfg.include_drafting:
        (refs_dir / "起草要点与范例.md").write_text(
            _generate_drafting_md(cfg), encoding="utf-8",
        )

    # Export CSV
    csv_content = _generate_rules_csv(grouped)
    (export_dir / "rules.csv").write_text(
        "﻿" + csv_content, encoding="utf-8",  # BOM for Excel
    )

    file_count = sum(1 for _ in skill_dir.rglob("*") if _.is_file())

    return BuiltSkill(
        skill_id=skill_id,
        domain_name=cfg.domain_name,
        folder_name=folder_name,
        output_dir=skill_dir,
        zip_path=None,
        file_count=file_count,
        rule_count=len(active_rules),
        dimension_stats=dimension_stats,
    )


def build_skill_zip(
    rules: list[dict],
    cfg: SkillConfig,
    skill_id: str,
    output_root: Path | None = None,
) -> BuiltSkill:
    """Build skill directory + create ZIP archive."""
    result = build_skill(rules, cfg, skill_id, output_root)

    root = output_root or _SKILL_OUTPUT_DIR
    zip_path = root / skill_id / f"{result.folder_name}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in result.output_dir.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(result.output_dir.parent)
                zf.write(file_path, arcname)

    result.zip_path = zip_path
    return result


# ── Serialization ────────────────────────────────────────────────────

def built_skill_to_dict(skill: BuiltSkill) -> dict[str, Any]:
    return {
        "skill_id": skill.skill_id,
        "domain_name": skill.domain_name,
        "folder_name": skill.folder_name,
        "file_count": skill.file_count,
        "rule_count": skill.rule_count,
        "dimension_stats": skill.dimension_stats,
        "download_url": f"/api/batches/{skill.skill_id}/exports/skill-zip" if skill.zip_path else None,
    }
