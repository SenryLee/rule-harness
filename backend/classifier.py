"""LLM-first document classification engine.

Two-phase classification:
    Phase 1 (instant): keyword pre-screening from filename + first 500 chars
    Phase 2 (LLM):     filename + first 2000 chars → structured JSON

Output dimensions:
    - document_genre:  7 categories (what the document IS)
    - authority_level: 5 tiers (how authoritative it is)
    - feature_tags:    boolean flags (redline, case, comments, template, etc.)
    - industry_hints:  detected industry keywords

The classifier also maps results back to legacy source_tag / is_redline / is_case
values so the existing pipeline system (P1-P5) continues to work unchanged.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Enums ────────────────────────────────────────────────────────────

DOCUMENT_GENRES = (
    "法律法规",
    "监管与司法文件",
    "裁判文书",
    "合同文本",
    "企业内部文件",
    "已有规则库",
    "专业参考资料",
)

AUTHORITY_LEVELS = (
    "L1-国家立法",
    "L2-司法解释与监管",
    "L3-企业强制",
    "L4-企业推荐",
    "L5-实践参考",
)

# authority_level → conflict priority (lower = higher priority)
_AUTHORITY_PRIORITY: dict[str, int] = {
    "L1-国家立法": 1,
    "L2-司法解释与监管": 1,
    "L3-企业强制": 2,
    "L4-企业推荐": 3,
    "L5-实践参考": 5,
}


@dataclass
class ClassificationResult:
    """Full classification output for one document."""
    document_genre: str
    authority_level: str
    confidence: float
    feature_tags: dict[str, bool]
    industry_hints: list[str]
    reasoning: str
    evidence: list[str]
    # Legacy mappings for pipeline compatibility
    source_tag: str
    source_priority: int
    is_redline: bool
    is_case: bool
    # v1.2 置信仲裁：LLM 与关键词预筛分歧且 LLM 置信不足时，
    # 标记需人工确认并给出备选体裁，前端高亮让用户二选一。
    needs_confirmation: bool = False
    alternative_genre: str = ""


# ── Phase 1: Keyword pre-screening ──────────────────────────────────
# v1.2：词表统一迁移到 backend/classification/taxonomy.yaml；
# 下面的内置列表仅作为 taxonomy 加载失败时的兜底。

_FALLBACK_GENRE_RULES: list[dict[str, Any]] = [
    {
        "genre": "已有规则库",
        "filename_kw": ("规则", "规则库", "审查清单", "审查意见", "审核要点", "规则项导入",
                        "审查手册", "审核指引", "审查指引", "合同审核", "合同审查", "审核手册"),
        "body_kw": ("规则项id", "规则编号", "检查项", "审查要求", "风险等级", "是否启用"),
        "suffixes": {".csv", ".tsv"},
        "weight": 6,
    },
    # 专业参考资料优先级提高，放在裁判文书和法律法规之前
    # 这样「手册」「指引」「操作指引」「风控」等能优先命中参考资料
    {
        "genre": "专业参考资料",
        "filename_kw": ("手册", "指南", "操作指引", "风控", "风险提示",
                        "教程", "培训", "讲义", "论文", "报告", "研究",
                        "书籍", "实务", "律师办理", "业务操作"),
        "body_kw": ("编委会", "主编", "撰稿人", "律师事务所", "律师协会",
                    "摘要", "参考文献", "目录", "第一章", "引言",
                    "风险提示", "防范措施", "建议", "实务要点"),
        "weight": 5,
    },
    {
        "genre": "裁判文书",
        # 关键改动：去掉「案例」（太宽泛），只保留裁判文书的硬信号
        "filename_kw": ("判决书", "裁定书", "民事判决", "刑事判决", "行政判决",
                        "仲裁裁决", "纠纷案", "抗诉", "再审"),
        "body_kw": ("判决如下", "裁定如下", "本院认为", "原告", "被告",
                    "上诉人", "被上诉人", "仲裁庭", "驳回"),
        # 反向信号：如果文件名含这些词，大幅降低裁判文书得分
        "anti_filename_kw": ("手册", "指引", "指南", "操作", "风控", "风险提示", "培训"),
        "weight": 5,
    },
    {
        "genre": "法律法规",
        # 关键改动：去掉宽泛的「法规」（文件名含"法律法规"的参考资料会误触）
        "filename_kw": ("中华人民共和国", "公司法", "民法典", "合同法", "条例", "细则"),
        "body_kw": ("全国人民代表大会", "主席令", "中华人民共和国", "自公布之日起施行"),
        "anti_filename_kw": ("手册", "指引", "指南", "操作", "律师", "风控", "相关"),
        "weight": 5,
    },
    {
        "genre": "监管与司法文件",
        # 关键改动：去掉「指引」「人民法院」（操作指引、法院出的手册会误触）
        "filename_kw": ("司法解释", "答记者问", "通知", "办法", "规定",
                        "证监会", "财政部", "国资委", "裁判指引"),
        "body_kw": ("最高人民法院", "司法解释", "法释", "解释如下", "证监会",
                    "财政部", "国资委", "各省", "印发"),
        "anti_filename_kw": ("手册", "操作指引", "律师", "风控"),
        "weight": 4,
    },
    {
        "genre": "企业内部文件",
        "filename_kw": ("制度", "红线", "底线", "内控", "操作规程", "管理规范",
                        "流程", "谈判清单", "审批", "不可接受"),
        "body_kw": ("红线", "底线", "不可接受", "内部制度", "内控", "审批流程",
                    "公司规定", "操作规程"),
        "weight": 3,
    },
    {
        "genre": "合同文本",
        # 关键改动：合同需要更强的信号才能匹配；加入反向信号
        "filename_kw": ("合同", "协议", "补充协议", "模板", "范本", "示范文本"),
        "body_kw": ("甲方", "乙方", "违约责任", "争议解决", "合同生效",
                    "签章", "盖章", "鉴于"),
        "anti_filename_kw": ("手册", "指引", "指南", "律师办理", "操作", "风控"),
        "weight": 2,
    },
]

def _genre_rules() -> list[dict[str, Any]]:
    from .classification import load_genre_rules

    return load_genre_rules() or _FALLBACK_GENRE_RULES


_REDLINE_KEYWORDS = ("红线", "底线", "不可接受", "退让", "谈判清单", "谈判底线")
_CASE_KEYWORDS = ("判决", "裁定", "裁判", "法院认为", "本院认为", "案例", "纠纷")
_TEMPLATE_KEYWORDS = ("模板", "范本", "示范文本", "合同样本", "格式合同")
_RULES_KEYWORDS = ("规则项", "规则编号", "检查项", "审查要求", "是否启用", "风险等级")
_CASE_FILENAME_RX = re.compile(r"[^\s]{1,16}诉[^\s]{1,32}(?:纠纷|案)")


def prescreen(filename: str, text: str) -> dict[str, Any]:
    """Fast keyword-based pre-screening. No API calls.

    v1.2：文件名/正文权重对调（文件名 1.5→0.8，正文 0.5→0.8），
    正文窗口从 500 字扩到 3000 字——文件名叫"案例汇编"的培训手册
    不应再被文件名一票拖走。
    """
    body_window = text[:3000]
    haystack = f"{filename}\n{body_window[:500]}"

    # Score each genre
    scores: list[tuple[str, float, list[str]]] = []
    for rule in _genre_rules():
        score = 0.0
        hits: list[str] = []
        for kw in rule["filename_kw"]:
            if kw in filename:
                score += rule["weight"] * 1.2
                hits.append(f"文件名:{kw}")
        for kw in rule["body_kw"]:
            count = body_window.count(kw)
            if count:
                score += min(count, 3) * rule["weight"] * 0.8
                hits.append(f"正文:{kw}")
        if "suffixes" in rule:
            from pathlib import Path
            if Path(filename).suffix.lower() in rule["suffixes"]:
                score += rule["weight"] * 2
                hits.append(f"扩展名:{Path(filename).suffix}")
        # Anti-signals: strongly penalise if filename contains exclusion keywords
        for anti_kw in rule.get("anti_filename_kw", ()):
            if anti_kw in filename:
                score *= 0.15  # reduce to 15%
                hits.append(f"反向:{anti_kw}")
                break  # one anti-signal is enough
        if score > 0:
            scores.append((rule["genre"], score, hits))

    scores.sort(key=lambda x: x[1], reverse=True)
    genre = scores[0][0] if scores else "合同文本"
    evidence = scores[0][2][:5] if scores else ["未命中强线索，默认合同文本"]
    # v1.2：权重改标定（文件名 1.5→1.2、正文 0.5→0.8/3000字窗口），分母同步 20→16
    confidence = min(0.75, 0.2 + (scores[0][1] / 16 if scores else 0))

    # Detect feature tags
    tags = {
        "is_redline": any(kw in haystack for kw in _REDLINE_KEYWORDS),
        "is_case": any(kw in haystack for kw in _CASE_KEYWORDS) or bool(_CASE_FILENAME_RX.search(filename)),
        "is_template": any(kw in haystack for kw in _TEMPLATE_KEYWORDS),
        "has_rules": any(kw in haystack for kw in _RULES_KEYWORDS),
    }

    # Refine genre based on tags
    if tags["is_case"] and genre != "裁判文书":
        if any(kw in filename for kw in ("判决", "裁定", "裁判", "纠纷")):
            genre = "裁判文书"
    if tags["has_rules"] and genre != "已有规则库":
        from pathlib import Path
        if Path(filename).suffix.lower() in {".csv", ".tsv", ".xlsx"}:
            genre = "已有规则库"

    return {
        "genre": genre,
        "confidence": confidence,
        "evidence": evidence,
        "feature_tags": tags,
    }


# ── Phase 2: LLM classification ─────────────────────────────────────

_LLM_CLASSIFY_SYSTEM = """你是一个法律文档分类专家。根据文件名和正文摘要，判断该文件的分类。

## 文档体裁（7选1，必须选一个）

1. **法律法规** — 全国人大/国务院发布的法律、行政法规（如民法典、公司法、XX条例）
2. **监管与司法文件** — 司法解释、部门规章、监管通知、裁判指引、答记者问、地方红头文件
3. **裁判文书** — 判决书、裁定书、仲裁裁决书、案例分析/评述
4. **合同文本** — 已签合同、合同模板/范本、补充协议、变更函
5. **企业内部文件** — 公司制度、审批流程、操作规程、红线/底线清单、内控规范
6. **已有规则库** — CSV/Excel规则表、审查清单、审查手册（含结构化的检查项和审查要求）
7. **专业参考资料** — 法律书籍、学术论文、行业报告、培训材料

## 权威层级（5选1）

- L1-国家立法：法律、行政法规
- L2-司法解释与监管：司法解释、部门规章、监管通知、裁判指引
- L3-企业强制：公司红线、强制性内部制度、审批底线
- L4-企业推荐：推荐性制度、标准条款库、操作指引、合同模板
- L5-实践参考：历史合同、裁判文书、书籍、论文、行业报告

## 特征标签（全部判断 true/false）

- is_redline: 是否包含谈判红线、底线、不可逾越条件
- is_case: 是否为裁判文书或案例分析
- is_template: 是否为合同模板或范本（而非已签署合同）
- has_rules: 是否已包含结构化的规则/检查项（CSV、审查清单格式）

## 行业领域检测

从正文中识别所属行业领域关键词（如：建工、房地产、金融、医药、IT等），返回0-3个。

返回严格 JSON（不要多余文字）：
{
  "document_genre": "7选1",
  "authority_level": "L1-国家立法 / L2-司法解释与监管 / L3-企业强制 / L4-企业推荐 / L5-实践参考",
  "confidence": 0.0到1.0,
  "feature_tags": {
    "is_redline": false,
    "is_case": false,
    "is_template": false,
    "has_rules": false
  },
  "industry_hints": [],
  "reasoning": "一句话分类依据"
}"""


async def classify_with_llm(
    filename: str,
    text: str,
    router: Any,
    headings: list[str] | None = None,
) -> dict[str, Any] | None:
    """Call LLM for precise classification. Returns None on failure.

    v1.2：text 应为多点采样文本（头/中/尾），并可附标题列表——
    标题对区分"手册 vs 法规 vs 合同"的区分度远高于正文前 2000 字。
    """
    headings_text = ""
    if headings:
        headings_text = "\n\n文档标题结构（前20个）:\n" + "\n".join(headings[:20])
    user_msg = f"文件名: {filename}{headings_text}\n\n正文采样（头部/中部/尾部）:\n{text[:3000]}"
    try:
        result = await router.chat_json(
            system=_LLM_CLASSIFY_SYSTEM,
            user=user_msg,
            temperature=0.1,
        )
        # Validate genre
        genre = result.get("document_genre", "")
        if genre not in DOCUMENT_GENRES:
            logger.warning("LLM returned invalid genre: %s", genre)
            return None
        return result
    except Exception as exc:
        logger.warning("LLM classification failed for %s: %s", filename, exc)
        return None


# ── Merge & Map ──────────────────────────────────────────────────────

def merge_results(
    pre: dict[str, Any],
    llm: dict[str, Any] | None,
) -> ClassificationResult:
    """Merge pre-screening and LLM results（v1.2 置信仲裁）。

    - 一致 → 取两者置信度较高者；
    - 分歧且 LLM 置信 ≥ 0.8 → 采纳 LLM；
    - 分歧且 LLM 置信 < 0.8 → 仍展示 LLM 结论，但 needs_confirmation=True，
      附 alternative_genre（预筛结论）和双方证据，由前端让用户一键二选一。
    不再是"LLM 一票否决预筛"。
    """
    needs_confirmation = False
    alternative_genre = ""

    if llm and llm.get("document_genre") in DOCUMENT_GENRES:
        genre = llm["document_genre"]
        authority = llm.get("authority_level", _infer_authority(genre, {}))
        confidence = float(llm.get("confidence", 0.8))
        tags = llm.get("feature_tags", {})
        industry = llm.get("industry_hints", [])
        reasoning = llm.get("reasoning", "")
        evidence = [f"LLM: {reasoning}"]

        pre_genre = pre.get("genre", "")
        pre_conf = float(pre.get("confidence", 0.0))
        if pre_genre == genre:
            confidence = max(confidence, pre_conf)
        elif confidence < 0.8 and pre_conf >= 0.3:
            needs_confirmation = True
            alternative_genre = pre_genre
            evidence.append(
                f"预筛分歧: {pre_genre}（{'；'.join(pre.get('evidence', [])[:3])}）"
            )

        # Merge pre-screening tags (OR logic — if either detected it, flag it)
        pre_tags = pre.get("feature_tags", {})
        merged_tags = {
            "is_redline": bool(tags.get("is_redline") or pre_tags.get("is_redline")),
            "is_case": bool(tags.get("is_case") or pre_tags.get("is_case")),
            "is_template": bool(tags.get("is_template") or pre_tags.get("is_template")),
            "has_rules": bool(tags.get("has_rules") or pre_tags.get("has_rules")),
        }
    else:
        genre = pre["genre"]
        authority = _infer_authority(genre, pre.get("feature_tags", {}))
        confidence = float(pre.get("confidence", 0.3))
        merged_tags = pre.get("feature_tags", {})
        industry = []
        reasoning = "仅关键词预筛（LLM未调用或失败）"
        evidence = pre.get("evidence", [])

    # Ensure valid authority
    if authority not in AUTHORITY_LEVELS:
        authority = _infer_authority(genre, merged_tags)

    # Map to legacy values
    source_tag = _map_to_source_tag(genre, merged_tags)
    priority = _AUTHORITY_PRIORITY.get(authority, 5)

    return ClassificationResult(
        document_genre=genre,
        authority_level=authority,
        confidence=confidence,
        feature_tags=merged_tags,
        industry_hints=list(industry)[:3],
        reasoning=reasoning,
        evidence=evidence,
        source_tag=source_tag,
        source_priority=priority,
        is_redline=merged_tags.get("is_redline", False),
        is_case=merged_tags.get("is_case", False) or genre == "裁判文书",
        needs_confirmation=needs_confirmation,
        alternative_genre=alternative_genre,
    )


def _infer_authority(genre: str, tags: dict[str, bool]) -> str:
    """Infer authority level from genre when LLM didn't provide one."""
    mapping: dict[str, str] = {
        "法律法规": "L1-国家立法",
        "监管与司法文件": "L2-司法解释与监管",
        "裁判文书": "L5-实践参考",
        "合同文本": "L5-实践参考",
        "企业内部文件": "L3-企业强制" if tags.get("is_redline") else "L4-企业推荐",
        "已有规则库": "L4-企业推荐",
        "专业参考资料": "L5-实践参考",
    }
    return mapping.get(genre, "L5-实践参考")


def _map_to_source_tag(genre: str, tags: dict[str, bool]) -> str:
    """Map new genre + tags to legacy source_tag for pipeline compatibility."""
    if genre == "法律法规":
        return "法规"
    if genre == "监管与司法文件":
        return "法规"
    if genre == "裁判文书":
        return "案例"
    if genre == "合同文本":
        if tags.get("is_template"):
            return "合同模板"
        return "历史合同"
    if genre == "企业内部文件":
        if tags.get("is_redline"):
            return "公司红线"
        return "内部制度"
    if genre == "已有规则库":
        return "标准条款库"
    if genre == "专业参考资料":
        return "业务规范"
    return "历史合同"


# ── Public API ───────────────────────────────────────────────────────

async def classify_document(
    filename: str,
    text: str,
    router: Any | None = None,
    skip_llm: bool = False,
    headings: list[str] | None = None,
) -> ClassificationResult:
    """Full two-phase classification.

    Args:
        filename: original filename
        text: preview text（v1.2 起为头/中/尾多点采样文本）
        router: LLMRouter instance. If None, LLM phase is skipped.
        skip_llm: force skip LLM even if router is available
        headings: 文档标题列表（可选，提高体裁区分度）
    """
    pre = prescreen(filename, text)
    llm_result = None

    if router and not skip_llm:
        llm_result = await classify_with_llm(filename, text, router, headings=headings)

    return merge_results(pre, llm_result)


def classify_document_sync(filename: str, text: str) -> ClassificationResult:
    """Synchronous classification using only keyword pre-screening."""
    pre = prescreen(filename, text)
    return merge_results(pre, None)


# ── Serialization ────────────────────────────────────────────────────

def classification_to_dict(result: ClassificationResult) -> dict[str, Any]:
    return {
        "document_genre": result.document_genre,
        "authority_level": result.authority_level,
        "confidence": result.confidence,
        "feature_tags": result.feature_tags,
        "industry_hints": result.industry_hints,
        "reasoning": result.reasoning,
        "evidence": result.evidence,
        "source_tag": result.source_tag,
        "source_priority": result.source_priority,
        "is_redline": result.is_redline,
        "is_case": result.is_case,
        "needs_confirmation": result.needs_confirmation,
        "alternative_genre": result.alternative_genre,
    }
