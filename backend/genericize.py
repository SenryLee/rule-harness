"""合同抽取优化 · 实例事实检测与通用化（机制2）。

历史合同里"某某有限公司应在 2024 年 3 月 31 日前支付 500 万元"这类条款，
被原样抽出就把具体当事人/日期当成了通用规则——这是脏数据的主因。

两层处理：
  1) 本地检测器 detect_instance_facts：纯规则识别具名主体/具体日期/证件号/账号/合同编号；
     命中即把规则标 generalizable="实例"，并把检出事实写入 instance_facts（审计）。
  2) LLM 泛化重写 genericize_instances（config 可关）：仅对命中的 instance 来源规则，
     把具名主体改写成角色词、剥离一次性事实，重写后再过一遍检测器；
     干净则回填 generalizable="通用"，仍残留则标"待定"留待人工确认。失败一律回退保留原文。
"""
from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import Any

from .config import Config
from .harness import take_excerpt
from .parsers import RuleCandidate

logger = logging.getLogger(__name__)

# ── 实例特定事实检测 ────────────────────────────────────────────────

# 具名主体：真实公司/机构名（排除"甲方/乙方/目标公司"等角色词）
_ORG_SUFFIX = r"(?:有限公司|有限责任公司|股份有限公司|集团有限公司|分公司|子公司|事务所|股份公司|合伙企业)"
_ORG_RX = re.compile(rf"[一-鿿]{{2,20}}{_ORG_SUFFIX}")
# 角色/泛指前缀：以这些词收尾的"公司"不算具名主体
_GENERIC_ORG_PREFIX = (
    "甲方", "乙方", "丙方", "丁方", "转让方", "受让方", "出让方", "买方", "卖方",
    "目标", "对方", "双方", "各方", "本", "该", "相应", "上述", "前述", "任一方",
    "守约方", "违约方", "发包方", "承包方", "出租方", "承租方", "委托方", "受托方",
)

# 具体日期
_DATE_RX = re.compile(
    r"(?:19|20)\d{2}\s*年\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?"
    r"|(?:19|20)\d{2}[-/.]\d{1,2}[-/.]\d{1,2}"
)
# 统一社会信用代码 / 身份证 / 长数字账号
# 注意：CJK 字符在 Python 正则里属于 \w，\b 紧邻中文会失效，故用 ASCII 字母数字负向断言定边界
_USCC_RX = re.compile(r"(?<![0-9A-Za-z])[0-9A-HJ-NP-RT-UW-Z]{18}(?![0-9A-Za-z])")
_IDCARD_RX = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_ACCOUNT_RX = re.compile(r"(?<!\d)\d{12,}(?!\d)")
# 合同/协议编号
_CONTRACT_NO_RX = re.compile(r"(?:合同|协议|文件)?编号[:：]\s*[A-Za-z0-9一-鿿\-]{3,}")
# 具名自然人：2-4 字中文姓名 + 先生/女士/身份证
_PERSON_RX = re.compile(r"[一-鿿]{2,4}(?:先生|女士)")


def _named_orgs(text: str) -> list[str]:
    hits: list[str] = []
    for m in _ORG_RX.finditer(text):
        name = m.group(0)
        # 去掉角色前缀后若主体名为空，视为泛指（如"目标公司""甲方公司"）
        core = name
        for pre in _GENERIC_ORG_PREFIX:
            if core.startswith(pre):
                core = core[len(pre):]
        # 主体名去掉后缀后还剩 ≥2 个非角色字，才算具名
        stem = re.sub(_ORG_SUFFIX, "", core)
        if len(stem) >= 2:
            hits.append(name)
    return hits


def detect_instance_facts(*texts: str) -> list[str]:
    """检测实例特定事实，返回去重后的命中片段列表（空=可视为通用）。"""
    blob = "\n".join(t for t in texts if t)
    if not blob:
        return []
    facts: list[str] = []
    facts.extend(_named_orgs(blob))
    facts.extend(_DATE_RX.findall(blob))
    facts.extend(_USCC_RX.findall(blob))
    facts.extend(_IDCARD_RX.findall(blob))
    facts.extend(_CONTRACT_NO_RX.findall(blob))
    facts.extend(_PERSON_RX.findall(blob))
    # 账号：排除已被日期/证件命中的数字
    for acc in _ACCOUNT_RX.findall(blob):
        if not _IDCARD_RX.fullmatch(acc) and acc not in facts:
            facts.append(acc)
    return list(dict.fromkeys(f.strip() for f in facts if f.strip()))


def _rule_texts(rule: RuleCandidate) -> tuple[str, ...]:
    return (rule.subject, rule.check_item, rule.requirement, rule.notes)


def annotate_generalizable(candidates: list[RuleCandidate]) -> list[RuleCandidate]:
    """本地标注 generalizable / instance_facts（纯 CPU）。"""
    out: list[RuleCandidate] = []
    for rule in candidates:
        facts = detect_instance_facts(*_rule_texts(rule))
        if facts:
            out.append(replace(
                rule,
                generalizable="实例",
                instance_facts="；".join(facts[:8]),
            ))
        else:
            out.append(replace(rule, generalizable="通用", instance_facts=""))
    return out


# ── LLM 泛化重写 ────────────────────────────────────────────────────

_GENERICIZE_SYSTEM = """你是法务规则通用化专家。输入是若干条从历史合同抽出的审查规则，\
它们含有"实例特定事实"（具名当事人、具体日期、证件号、账号、一次性交易细节）。\
你的任务：把每条规则改写成可复用的通用审查规则。

规则：
1. 具名主体改成角色词（如"华润置地有限公司"→"出让方/转让方"，按上下文判断角色；判断不了用"相应一方"）。
2. 删除具体日期/证件号/账号/合同编号等一次性事实；若某日期是"约定期限"的载体，改写成"约定期限内"。
3. 不要新增原文没有的数值或阈值；阈值是规则实质的（如违约金 30%）要保留。
4. check_item ≤ 40 字；requirement 保持专业审查口径。
5. 若一条规则去掉实例事实后已无通用价值（纯一次性事实、无可复用规范），把 keep 设为 false。
6. v2.0 新增：source_excerpt 字段——从改写后的 requirement 出发，回到原文块中摘录 30-150 字\
   最直接支撑该规则的原文片段。摘录必须是原文的逐字子串，不得改写或编造。

严格输出 JSON：{"rules":[{"idx":int,"keep":bool,"subject":str,"check_item":str,"requirement":str,"source_excerpt":str}]}\
不要输出多余文字。"""


def _needs_genericize(rule: RuleCandidate) -> bool:
    return (
        rule.generalizable == "实例"
        and rule.source_role in {"instance", "template"}
        and rule.output_target == "main"
    )


async def genericize_instances(
    candidates: list[RuleCandidate],
    router: Any,
    cfg: Config,
    batch_size: int = 8,
) -> list[RuleCandidate]:
    """对命中实例事实的 instance/template 规则做 LLM 泛化重写。

    config.extraction.genericize_instances 关闭、router 不可用、或无命中规则时，
    原样返回（已带本地 generalizable 标记）。任何调用失败回退保留原文并标"待定"。
    """
    if not getattr(cfg.extraction, "genericize_instances", True) or router is None:
        return candidates

    targets = [(i, r) for i, r in enumerate(candidates) if _needs_genericize(r)]
    if not targets:
        return candidates

    out = list(candidates)
    for start in range(0, len(targets), batch_size):
        chunk = targets[start:start + batch_size]
        payload = [
            {
                "idx": i,
                "subject": r.subject,
                "check_item": r.check_item,
                "requirement": r.requirement,
                "instance_facts": r.instance_facts,
                # v2.0: 传入原文块供 LLM 摘录新 source_excerpt
                "source_text": r.raw_block_text[:2000] if r.raw_block_text else "",
            }
            for i, r in chunk
        ]
        try:
            obj = await router.chat_json(
                system=_GENERICIZE_SYSTEM,
                user="待通用化规则：\n" + _dumps(payload),
                temperature=0.1,
            )
            rewrites = {item["idx"]: item for item in obj.get("rules", []) if "idx" in item}
        except Exception as exc:  # noqa: BLE001 - 失败回退，不阻断主流程
            logger.warning("genericize batch failed: %s", exc)
            for i, _ in chunk:
                out[i] = replace(out[i], generalizable="待定")
            continue

        for i, rule in chunk:
            rw = rewrites.get(i)
            if not rw:
                out[i] = replace(rule, generalizable="待定")
                continue
            if rw.get("keep") is False:
                out[i] = replace(rule, generalizable="实例", output_target="discarded",
                                 scope_reason="纯实例事实，无通用价值")
                continue
            new_subject = (rw.get("subject") or rule.subject).strip()
            new_check = (rw.get("check_item") or rule.check_item).strip()
            new_req = (rw.get("requirement") or rule.requirement).strip()
            residual = detect_instance_facts(new_subject, new_check, new_req)
            # v2.0: 重新取摘录——改写后的 requirement 可能对应原文不同片段
            new_excerpt, excerpt_fallback = take_excerpt(rw, rule.raw_block_text)
            out[i] = replace(
                rule,
                subject=new_subject,
                check_item=new_check,
                requirement=new_req,
                source_excerpt=new_excerpt,
                excerpt_fallback=excerpt_fallback,
                genericized=True,  # v2.0: 标记规则经通用化重写
                generalizable="通用" if not residual else "待定",
                instance_facts="" if not residual else "；".join(residual[:8]),
            )
    return out


def _dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
