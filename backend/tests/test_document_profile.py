from __future__ import annotations

from backend.document_profile import profile_document
from backend.preview import preview_classify_text


def test_profile_local_red_head_file():
    result = profile_document(
        "北京市国资委关于规范企业国有产权转让有关事项的通知.docx",
        "各有关单位：为加强企业国有资产监管，规范产权交易和资产评估程序，现印发本通知。",
    )

    assert result["document_type"] == "地方红头文件"
    assert result["authority_level"] == "地方规范性文件"
    assert result["primary_legal_topic"] == "国资监管"
    assert "国资审批/产权交易" in result["secondary_scenarios"]
    assert result["classification_mode"] in {"medium", "high"}


def test_profile_judicial_interpretation_and_national_law():
    interpretation = profile_document(
        "最高人民法院关于适用《中华人民共和国公司法》若干问题的规定.docx",
        "最高人民法院审判委员会通过，现就公司法适用问题解释如下。",
    )
    law = profile_document(
        "中华人民共和国公司法.docx",
        "中华人民共和国主席令。全国人民代表大会常务委员会修订，公司章程、股东会、董事会依照本法执行。",
    )

    assert interpretation["document_type"] == "司法解释"
    assert interpretation["authority_level"] == "司法解释"
    assert interpretation["primary_legal_topic"] == "公司法"
    assert law["document_type"] == "国家法律"
    assert law["authority_level"] == "国家法律"
    assert law["primary_legal_topic"] == "公司法"


def test_profile_regulatory_notice_is_not_local_red_head():
    result = profile_document(
        "中国证券监督管理委员会关于加强对上市公司非流通股协议转让活动规范管理的通知.docx",
        "中国证券监督管理委员会要求加强协议转让规范管理，涉及信息披露、登记结算和监管要求。",
    )

    assert result["document_type"] == "部门规章/监管通知"
    assert result["authority_level"] == "部门规章/监管文件"
    assert result["processing_suggestion"].startswith("作为监管规则处理")


def test_profile_judicial_qa_is_not_judicial_interpretation():
    result = profile_document(
        "最高人民法院民二庭负责人就《关于适用公司法若干问题的规定（三）》答记者问.docx",
        "最高人民法院民二庭负责人就司法解释适用问题答记者问，说明出资责任和股权转让问题。",
    )

    assert result["document_type"] == "司法问答/解释性材料"
    assert result["authority_level"] == "司法解释资料/立法资料"


def test_profile_local_court_guidance_is_judicial_guidance():
    result = profile_document(
        "广西壮族自治区高级人民法院民二庭关于审理公司纠纷案件若干问题的裁判指引.docx",
        "高级人民法院发布裁判指引，涉及公司纠纷、证据规则、股东知情权和优先购买权。",
    )

    assert result["document_type"] == "地方司法裁判指引"
    assert result["authority_level"] == "地方司法文件/裁判口径"


def test_profile_equity_transfer_contract():
    result = profile_document(
        "股权转让合同.docx",
        "转让方将其持有的目标公司股权转让给受让方，双方约定交割、付款、工商变更和股东名册变更事项。",
    )

    assert result["document_type"] == "股权转让合同"
    assert result["authority_level"] == "合同文本"
    assert result["primary_legal_topic"] == "公司法"
    assert "股权转让" in result["secondary_scenarios"]
    assert "工商登记/变更" in result["secondary_scenarios"]


def test_profile_existing_rules_csv():
    result = profile_document(
        "主动导出规则.csv",
        "rule_id,rule_text,source_file,contract_types,confidence\nR001,付款期限应明确,合同审核指引,通用商事,0.9",
    )

    assert result["document_type"] == "已有规则CSV"
    assert result["authority_level"] == "内部规则库"
    assert "规则导入" in result["secondary_scenarios"]
    assert result["classification_mode"] == "high"


def test_profile_gift_property_keeps_real_estate_secondary():
    result = profile_document(
        "夫妻间赠与房产的处理.docx",
        "夫妻一方将名下房产赠与另一方，涉及不动产登记、赠与合同撤销与共有财产认定。",
    )

    assert result["primary_legal_topic"] == "合同法/赠与"
    assert "房地产/不动产" in result["secondary_scenarios"]
    assert result["primary_legal_topic"] != "房地产"


def test_preview_response_includes_document_profile():
    result = preview_classify_text(
        "股权转让合同.docx",
        "转让方将目标公司股权转让给受让方，并办理工商变更登记。",
    )

    assert result["suggested_source_tag"]
    assert "document_profile" in result
    assert result["document_profile"]["document_type"] == "股权转让合同"
