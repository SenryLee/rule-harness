import pytest

from backend.harness import (
    CONTRACT_TYPE_MAP,
    RULE_TYPE_MAP,
    THEME_KEYS,
    build_rule_id,
    compute_fingerprint,
    keyword_appears_in_excerpt,
    load_theme_keys,
    normalize_text,
    validate_atomic,
)


class TestFingerprint:
    def test_same_theme_subject_predicate_same_fingerprint(self):
        r1 = {
            "theme_key": "confidentiality.term",
            "subject": "受信方",
            "predicate": "不得短于",
            "threshold_type": "期限",
            "direction": "反向",
        }
        r2 = dict(r1)
        assert compute_fingerprint(r1) == compute_fingerprint(r2)

    def test_different_theme_different_fingerprint(self):
        r1 = {
            "theme_key": "confidentiality.term",
            "subject": "受信方",
            "predicate": "不得短于",
            "threshold_type": "期限",
            "direction": "反向",
        }
        r2 = {**r1, "theme_key": "liability.damages.cap"}
        assert compute_fingerprint(r1) != compute_fingerprint(r2)

    def test_fingerprint_is_6_chars_uppercase(self):
        r = {
            "theme_key": "confidentiality.term",
            "subject": "受信方",
            "predicate": "不得短于",
            "threshold_type": "期限",
            "direction": "反向",
        }
        fp = compute_fingerprint(r)
        assert len(fp) == 6
        assert fp == fp.upper()

    def test_missing_fields_handled_gracefully(self):
        r: dict = {"theme_key": "test.key"}
        fp = compute_fingerprint(r)
        assert len(fp) == 6

    def test_empty_dict_returns_fingerprint(self):
        fp = compute_fingerprint({})
        assert len(fp) == 6

    def test_different_subject_different_fingerprint(self):
        r1 = {
            "theme_key": "payment.term.days",
            "subject": "买方",
            "predicate": "应在",
            "threshold_type": "期限",
            "direction": "正向",
        }
        r2 = {**r1, "subject": "卖方"}
        assert compute_fingerprint(r1) != compute_fingerprint(r2)

    def test_different_direction_different_fingerprint(self):
        r1 = {
            "theme_key": "payment.term.days",
            "subject": "买方",
            "predicate": "应在",
            "threshold_type": "期限",
            "direction": "正向",
        }
        r2 = {**r1, "direction": "反向"}
        assert compute_fingerprint(r1) != compute_fingerprint(r2)


class TestBuildRuleId:
    def test_purchase_clause_rule(self):
        rule = {
            "rule_type": "clause",
            "theme_key": "payment.late_fee.cap_ratio",
            "subject": "违约方",
            "predicate": "不得超过",
            "threshold_type": "比例",
            "direction": "反向",
        }
        rid = build_rule_id(rule, ["采购"])
        assert rid.startswith("PUR-C-")
        assert len(rid) == 12  # PUR-C- + 6 hex = 12

    def test_compliance_rule(self):
        rule = {
            "rule_type": "governance",
            "theme_key": "compliance.donation.approval_threshold",
            "subject": "员工",
            "predicate": "应当报批",
            "threshold_type": "金额",
            "direction": "正向",
        }
        rid = build_rule_id(rule, ["通用商事"])
        assert rid.startswith("COM-G-")

    def test_negative_rule(self):
        rule = {
            "rule_type": "negative",
            "theme_key": "format_clause.invalid.final_interpretation",
            "subject": "格式条款提供方",
            "predicate": "禁止使用",
            "threshold_type": "列表",
            "direction": "反向",
        }
        rid = build_rule_id(rule, ["服务"])
        assert rid.startswith("SVC-N-")

    def test_wildcard_contract_type(self):
        rule = {
            "rule_type": "clause",
            "theme_key": "confidentiality.term",
            "subject": "受信方",
            "predicate": "不得短于",
            "threshold_type": "期限",
            "direction": "反向",
        }
        rid = build_rule_id(rule, ["*"])
        assert rid.startswith("ALL-C-")

    def test_sales_contract_type_maps_to_sls(self):
        rule = {
            "rule_type": "clause",
            "theme_key": "payment.term.days",
            "subject": "买方",
            "predicate": "应在",
            "threshold_type": "期限",
            "direction": "正向",
        }
        rid = build_rule_id(rule, ["销售"])
        assert rid.startswith("SLS-C-")

    def test_none_contract_types_falls_back_to_com(self):
        rule = {
            "rule_type": "clause",
            "theme_key": "confidentiality.term",
            "subject": "受信方",
            "predicate": "不得短于",
            "threshold_type": "期限",
            "direction": "反向",
        }
        rid = build_rule_id(rule, None)
        assert rid.startswith("COM-C-")

    def test_empty_contract_types_falls_back_to_com(self):
        rule = {
            "rule_type": "governance",
            "theme_key": "compliance.donation.restriction",
            "subject": "员工",
            "predicate": "不得",
            "threshold_type": "金额",
            "direction": "反向",
        }
        rid = build_rule_id(rule, [])
        assert rid.startswith("COM-G-")


class TestValidateAtomic:
    def test_valid_atomic_rule_passes(self):
        rule = {
            "check_item": "保密期限是否不少于3年",
            "requirement": "[条款] 保密期限不得少于3年",
            "notes": "核实保密期限条款",
            "risk_level": "高",
            "keywords": ["保密", "保密期限", "3年"],
            "theme_key": "confidentiality.term.duration",
        }
        failures = validate_atomic(rule)
        assert failures == []

    def test_check_item_too_long_fails(self):
        rule = {
            "check_item": "这是一个非常非常长的检查项，超过三十个字的限制应该被检测出来并报告错误",
            "requirement": "[条款] 测试",
            "notes": "",
            "risk_level": "中",
            "keywords": ["测试"],
            "theme_key": "payment.term.days",
        }
        failures = validate_atomic(rule)
        assert "check_item_too_long" in failures

    def test_connector_not_atomic_fails(self):
        rule = {
            "check_item": "违约金比例且封顶是否合规",
            "requirement": "[条款] 测试要求",
            "notes": "",
            "risk_level": "高",
            "keywords": ["违约金"],
            "theme_key": "payment.late_fee.cap_ratio",
        }
        failures = validate_atomic(rule)
        assert "check_item_not_atomic" in failures

    def test_connector_simultaneous_fails(self):
        rule = {
            "check_item": "违约金和赔偿上限",
            "requirement": "[条款] 测试要求",
            "notes": "",
            "risk_level": "高",
            "keywords": ["测试"],
            "theme_key": "payment.late_fee.cap_ratio",
        }
        failures = validate_atomic(rule)
        assert "check_item_not_atomic" in failures

    def test_connector_yiji_fails(self):
        rule = {
            "check_item": "违约金以及赔偿上限",
            "requirement": "[条款] 测试要求",
            "notes": "",
            "risk_level": "高",
            "keywords": ["测试"],
            "theme_key": "payment.late_fee.cap_ratio",
        }
        failures = validate_atomic(rule)
        assert "check_item_not_atomic" in failures

    def test_missing_type_tag_fails(self):
        rule = {
            "check_item": "测试检查项",
            "requirement": "缺少类型标签的要求",
            "notes": "",
            "risk_level": "中",
            "keywords": ["测试"],
            "theme_key": "payment.term.days",
        }
        failures = validate_atomic(rule)
        assert "requirement_missing_type_tag" in failures

    def test_hegui_tag_is_valid(self):
        rule = {
            "check_item": "捐赠审批流程",
            "requirement": "[合规] 捐赠需要审批",
            "notes": "",
            "risk_level": "中",
            "keywords": ["捐赠", "审批"],
            "theme_key": "compliance.donation.restriction",
        }
        failures = validate_atomic(rule)
        assert "requirement_missing_type_tag" not in failures

    def test_invalid_theme_key_fails(self):
        rule = {
            "check_item": "测试检查项",
            "requirement": "[条款] 测试要求",
            "notes": "",
            "risk_level": "中",
            "keywords": ["测试"],
            "theme_key": "this.key.does.not.exist.in.whitelist",
        }
        failures = validate_atomic(rule)
        assert "theme_key_not_in_whitelist" in failures

    def test_empty_theme_key_fails(self):
        rule = {
            "check_item": "测试检查项",
            "requirement": "[条款] 测试要求",
            "notes": "",
            "risk_level": "中",
            "keywords": ["测试"],
            "theme_key": "",
        }
        failures = validate_atomic(rule)
        assert "theme_key_not_in_whitelist" in failures

    def test_invalid_risk_level_fails(self):
        rule = {
            "check_item": "测试检查项",
            "requirement": "[条款] 测试要求",
            "notes": "",
            "risk_level": "超高",
            "keywords": ["测试"],
            "theme_key": "payment.term.days",
        }
        failures = validate_atomic(rule)
        assert "invalid_risk_level" in failures

    def test_keyword_count_zero_fails(self):
        rule = {
            "check_item": "测试检查项",
            "requirement": "[条款] 测试要求",
            "notes": "",
            "risk_level": "中",
            "keywords": [],
            "theme_key": "payment.term.days",
        }
        failures = validate_atomic(rule)
        assert "keyword_count_out_of_range" in failures

    def test_keyword_count_too_many_fails(self):
        rule = {
            "check_item": "测试检查项",
            "requirement": "[条款] 测试要求",
            "notes": "",
            "risk_level": "中",
            "keywords": ["a", "b", "c", "d", "e", "f", "g", "h", "i"],
            "theme_key": "payment.term.days",
        }
        failures = validate_atomic(rule)
        assert "keyword_count_out_of_range" in failures

    def test_requirement_too_long_fails(self):
        long_req = "[条款] " + "非常" * 100
        rule = {
            "check_item": "测试",
            "requirement": long_req,
            "notes": "",
            "risk_level": "中",
            "keywords": ["测试"],
            "theme_key": "payment.term.days",
        }
        failures = validate_atomic(rule)
        assert "requirement_too_long" in failures

    def test_string_keywords_parsed_as_list(self):
        rule = {
            "check_item": "保密期限",
            "requirement": "[条款] 保密期限要求",
            "notes": "",
            "risk_level": "高",
            "keywords": "保密,期限,合同",
            "theme_key": "confidentiality.term.duration",
        }
        failures = validate_atomic(rule)
        assert "keyword_count_out_of_range" not in failures


class TestKeywordAppearsInExcerpt:
    def test_exact_match(self):
        assert keyword_appears_in_excerpt("违约金", "乙方支付违约金")

    def test_fuzzy_match_no_punctuation(self):
        assert keyword_appears_in_excerpt("违约金", "乙方支付违约金。")

    def test_no_match(self):
        assert not keyword_appears_in_excerpt("保密", "乙方支付违约金")

    def test_substring_match(self):
        assert keyword_appears_in_excerpt("保密期限", "保密期限不少于3年")

    def test_empty_keyword_no_match(self):
        assert not keyword_appears_in_excerpt("", "乙方支付违约金")

    def test_empty_excerpt_no_match(self):
        assert not keyword_appears_in_excerpt("违约金", "")

    def test_both_empty_no_match(self):
        assert not keyword_appears_in_excerpt("", "")

    def test_case_insensitive_match(self):
        assert keyword_appears_in_excerpt("ABC", "abc内容")


class TestLoadThemeKeys:
    def test_theme_keys_loaded(self):
        keys = load_theme_keys()
        assert isinstance(keys, set)
        assert len(keys) > 50
        assert "confidentiality.term.duration" in keys
        assert "payment.late_fee.cap_ratio" in keys

    def test_cached_theme_keys_same_object(self):
        keys1 = load_theme_keys()
        keys2 = load_theme_keys()
        assert keys1 == keys2

    def test_theme_keys_contains_no_empty_strings(self):
        keys = load_theme_keys()
        for k in keys:
            assert k != ""
            assert k.strip() == k


class TestNormalizeText:
    def test_removes_punctuation(self):
        result = normalize_text("违约金。")
        assert "。" not in result

    def test_casefold_works(self):
        result = normalize_text("ABC")
        assert result == "abc"

    def test_preserves_cjk(self):
        result = normalize_text("违约金比例")
        assert "违约金比例" in result

    def test_handles_empty_string(self):
        result = normalize_text("")
        assert result == ""


class TestContractTypeMap:
    def test_known_types(self):
        assert CONTRACT_TYPE_MAP["采购"] == "PUR"
        assert CONTRACT_TYPE_MAP["服务"] == "SVC"
        assert CONTRACT_TYPE_MAP["通用商事"] == "COM"
        assert CONTRACT_TYPE_MAP["*"] == "ALL"

    def test_wildcard_maps_to_all(self):
        assert CONTRACT_TYPE_MAP["*"] == "ALL"


class TestRuleTypeMap:
    def test_all_types_mapped(self):
        assert RULE_TYPE_MAP["clause"] == "C"
        assert RULE_TYPE_MAP["governance"] == "G"
        assert RULE_TYPE_MAP["negative"] == "N"
