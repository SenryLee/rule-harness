from __future__ import annotations

from pathlib import Path
from typing import Any


_DOC_TYPE_RULES: list[dict[str, Any]] = [
    {
        "document_type": "已有规则CSV",
        "authority_level": "内部规则库",
        "processing_suggestion": "按已抽取规则导入或核验，不因资料画像减少规则覆盖。",
        "filename": ("规则", "规则库", "规则项", "审查意见", "导出"),
        "body": ("rule_id", "规则编号", "规则项", "审查意见", "风险等级", "source_file"),
        "suffixes": {".csv", ".tsv"},
        "weight": 4,
    },
    {
        "document_type": "司法问答/解释性材料",
        "authority_level": "司法解释资料/立法资料",
        "processing_suggestion": "将问答结论、负责人说明和适用边界转为可执行审查规则，不因其非正式条文而跳过。",
        "filename": ("答记者问", "负责人就", "审判实务问答", "系列问答"),
        "body": ("答记者问", "负责人", "问：", "答：", "记者", "审判实务问答"),
        "weight": 5,
    },
    {
        "document_type": "地方司法裁判指引",
        "authority_level": "地方司法文件/裁判口径",
        "processing_suggestion": "将裁判观点、审判口径和证据规则反推为事前审查规则。",
        "filename": ("高级人民法院", "中级人民法院", "裁判指引", "审判实务"),
        "body": ("高级人民法院", "中级人民法院", "裁判指引", "审判实务", "法院认为", "裁判观点"),
        "weight": 4,
    },
    {
        "document_type": "部门规章/监管通知",
        "authority_level": "部门规章/监管文件",
        "processing_suggestion": "作为监管规则处理，重点抽取禁止、审批、披露、登记、交易程序和拒办情形。",
        "filename": ("中国证券监督管理委员会", "证监会", "财政部", "监管", "规范管理", "国有股权转让管理办法"),
        "body": ("中国证券监督管理委员会", "证监会", "财政部", "监管", "规范管理", "信息披露", "登记结算", "产权交易"),
        "weight": 4,
    },
    {
        "document_type": "司法解释",
        "authority_level": "司法解释",
        "processing_suggestion": "作为司法裁判口径和规则依据处理，保留条文级抽取覆盖。",
        "filename": ("司法解释", "解释", "最高人民法院", "最高人民检察院"),
        "body": ("最高人民法院", "最高人民检察院", "审判委员会", "法释", "解释如下"),
        "weight": 4,
    },
    {
        "document_type": "国家法律",
        "authority_level": "国家法律",
        "processing_suggestion": "作为上位法依据处理，保留条文级抽取覆盖。",
        "filename": ("中华人民共和国", "公司法", "民法典", "合同法"),
        "body": ("全国人民代表大会", "全国人民代表大会常务委员会", "主席令", "中华人民共和国公司法", "中华人民共和国民法典"),
        "weight": 4,
    },
    {
        "document_type": "地方红头文件",
        "authority_level": "地方规范性文件",
        "processing_suggestion": "作为地方监管/主管部门规则处理，保留部门口径和适用范围。",
        "filename": ("通知", "意见", "办法", "指引", "规定", "国资委", "工商局", "市场监督管理局"),
        "body": ("国资委", "工商局", "市场监督管理局", "人民政府", "各区", "各有关单位", "印发", "通知"),
        "weight": 3,
    },
    {
        "document_type": "股权转让合同",
        "authority_level": "合同文本",
        "processing_suggestion": "作为合同样本处理，抽取交易条款、交割、付款和违约责任。",
        "filename": ("股权转让", "股权转让协议", "股权转让合同"),
        "body": ("股权转让", "转让方", "受让方", "目标公司", "工商变更", "股东名册", "交割"),
        "weight": 4,
    },
    {
        "document_type": "合同文本",
        "authority_level": "合同文本",
        "processing_suggestion": "作为合同正文处理，保留条款级抽取覆盖。",
        "filename": ("合同", "协议"),
        "body": ("甲方", "乙方", "违约责任", "争议解决", "合同生效"),
        "weight": 2,
    },
]

_TOPIC_RULES: list[dict[str, Any]] = [
    {
        "topic": "公司法",
        "keywords": (
            "公司法", "公司章程", "股东会", "董事会", "监事会", "法定代表人",
            "股权转让", "股东名册", "出资", "注册资本", "目标公司", "工商变更",
        ),
        "weight": 3,
    },
    {
        "topic": "证券监管/股权转让",
        "keywords": ("证监会", "证券监督管理", "上市公司", "非流通股", "协议转让", "信息披露", "登记结算"),
        "weight": 4,
    },
    {
        "topic": "合同法/赠与",
        "keywords": ("赠与", "赠与合同", "赠与人", "受赠人", "撤销赠与", "附条件赠与"),
        "weight": 5,
    },
    {
        "topic": "合同法",
        "keywords": ("合同", "协议", "甲方", "乙方", "违约责任", "解除合同", "争议解决", "付款"),
        "weight": 2,
    },
    {
        "topic": "房地产",
        "keywords": (
            "房地产", "房产", "房屋", "不动产", "商品房", "物业", "产权证",
            "不动产登记", "过户", "购房", "房屋买卖",
        ),
        "weight": 2,
    },
    {
        "topic": "国资监管",
        "keywords": ("国资委", "国有资产", "企业国有资产", "产权交易", "资产评估", "进场交易"),
        "weight": 3,
    },
    {
        "topic": "市场监管/工商登记",
        "keywords": ("工商", "市场监督管理", "登记机关", "营业执照", "企业登记", "工商变更"),
        "weight": 3,
    },
]

_SCENARIO_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("股权转让", ("股权转让", "转让方", "受让方", "目标公司", "交割")),
    ("工商登记/变更", ("工商变更", "企业登记", "登记机关", "营业执照", "股东名册")),
    ("国资审批/产权交易", ("国资委", "国有资产", "产权交易", "资产评估", "进场交易")),
    ("房地产/不动产", ("房地产", "房产", "房屋", "不动产", "不动产登记", "过户", "产权证")),
    ("赠与", ("赠与", "赠与合同", "受赠人", "撤销赠与")),
    ("规则导入", ("规则编号", "规则项", "审查意见", "风险等级", "source_file")),
]


def profile_document(filename: str, text: str) -> dict[str, Any]:
    """Return a rule-based P0 document profile without affecting extraction scope."""

    haystack = f"{filename}\n{text}"
    doc_type, doc_score, doc_evidence = _classify_document_type(filename, text)
    topic, topic_score, topic_evidence, topic_scores = _classify_primary_topic(haystack)
    secondary_scenarios = _classify_secondary_scenarios(haystack, topic)

    confidence = _confidence(doc_score, topic_score, len(doc_evidence) + len(topic_evidence))
    classification_mode = _classification_mode(confidence)
    evidence = [*doc_evidence[:4], *topic_evidence[:4]]
    if not evidence:
        evidence.append("未命中强画像线索")

    if topic == "房地产" and _gift_or_contract_stronger(topic_scores):
        topic = "合同法/赠与"
        if "房地产/不动产" not in secondary_scenarios:
            secondary_scenarios.insert(0, "房地产/不动产")
        evidence.append("赠与/合同线索强于房产线索，房产降为辅助场景")

    return {
        "document_type": doc_type["document_type"],
        "authority_level": doc_type["authority_level"],
        "processing_suggestion": doc_type["processing_suggestion"],
        "primary_legal_topic": topic,
        "secondary_scenarios": secondary_scenarios,
        "confidence": round(confidence, 2),
        "classification_mode": classification_mode,
        "evidence": evidence,
    }


def _classify_document_type(filename: str, text: str) -> tuple[dict[str, str], float, list[str]]:
    suffix = Path(filename).suffix.lower()
    forced = _forced_document_type(filename, suffix)
    if forced:
        rule, reason = forced
        return rule, 30.0, [reason]

    scores: list[tuple[dict[str, str], float, list[str]]] = []
    for rule in _DOC_TYPE_RULES:
        hits: list[str] = []
        score = 0.0
        if suffix in rule.get("suffixes", set()):
            score += 5
            hits.append(f"扩展名:{suffix}")
        for word in rule["filename"]:
            if word in filename:
                score += rule["weight"]
                hits.append(f"文件名:{word}")
        for word in rule["body"]:
            count = text.count(word)
            if count:
                score += min(count, 3) * (rule["weight"] * 0.6)
                hits.append(f"正文:{word}x{count}")
        if score > 0:
            scores.append((rule, score, hits))

    if not scores:
        return _DOC_TYPE_RULES[-1], 0.0, ["未命中强资料类型线索，默认合同文本"]

    scores.sort(key=lambda item: item[1], reverse=True)
    rule, score, hits = scores[0]
    return rule, score, [f"资料类型:{rule['document_type']}({', '.join(hits[:5])})"]


def _forced_document_type(filename: str, suffix: str) -> tuple[dict[str, str], str] | None:
    if suffix in {".csv", ".tsv"}:
        return _DOC_TYPE_RULES[0], f"资料类型:已有规则CSV(扩展名:{suffix})"
    for rule in _DOC_TYPE_RULES:
        doc_type = rule["document_type"]
        if doc_type == "司法问答/解释性材料" and "答记者问" in filename:
            return rule, "资料类型:司法问答/解释性材料(文件名:答记者问)"
        if (
            doc_type == "地方司法裁判指引"
            and "人民法院" in filename
            and ("裁判指引" in filename or "审判实务" in filename or "系列问答" in filename)
        ):
            return rule, "资料类型:地方司法裁判指引(文件名:人民法院/裁判指引)"
        if (
            doc_type == "部门规章/监管通知"
            and any(word in filename for word in ("中国证券监督管理委员会", "证监会", "财政部"))
        ):
            return rule, "资料类型:部门规章/监管通知(文件名:监管部门)"
    return None


def _classify_primary_topic(haystack: str) -> tuple[str, float, list[str], dict[str, float]]:
    scores: list[tuple[str, float, list[str]]] = []
    score_map: dict[str, float] = {}
    for rule in _TOPIC_RULES:
        hits: list[str] = []
        score = 0.0
        for word in rule["keywords"]:
            count = haystack.count(word)
            if not count:
                continue
            score += min(count, 4) * rule["weight"]
            hits.append(f"{word}x{count}")
        if score > 0:
            topic = str(rule["topic"])
            score_map[topic] = score
            scores.append((topic, score, hits))

    if not scores:
        return "通用商事", 0.0, ["未命中强法律主题线索，默认通用商事"], score_map

    scores.sort(key=lambda item: item[1], reverse=True)
    topic, score, hits = scores[0]
    return topic, score, [f"主法律主题:{topic}({', '.join(hits[:5])})"], score_map


def _classify_secondary_scenarios(haystack: str, primary_topic: str) -> list[str]:
    scenarios: list[str] = []
    for label, keywords in _SCENARIO_RULES:
        if any(word in haystack for word in keywords):
            scenarios.append(label)

    if primary_topic == "房地产":
        scenarios = [item for item in scenarios if item != "房地产/不动产"]
    if primary_topic == "合同法/赠与":
        scenarios = [item for item in scenarios if item != "赠与"]
    return scenarios[:5]


def _confidence(doc_score: float, topic_score: float, evidence_count: int) -> float:
    if doc_score <= 0 and topic_score <= 0:
        return 0.25
    raw = 0.25 + min(doc_score, 16) * 0.025 + min(topic_score, 24) * 0.018 + min(evidence_count, 6) * 0.03
    return min(0.95, raw)


def _classification_mode(confidence: float) -> str:
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.5:
        return "medium"
    return "low"


def _gift_or_contract_stronger(topic_scores: dict[str, float]) -> bool:
    real_estate = topic_scores.get("房地产", 0.0)
    gift = topic_scores.get("合同法/赠与", 0.0)
    contract = topic_scores.get("合同法", 0.0)
    return gift >= real_estate or gift + contract > real_estate
