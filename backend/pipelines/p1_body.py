from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ..config import Config
from ..harness import THEME_KEYS, map_theme_key, validate_atomic
from ..llm import LLMRouter, LLMTruncatedError
from ..parsers import ContentBlock, ParsedDocument, RuleCandidate
from .errors import record_llm_failure
from ..prompt_loader import PromptSections, load_prompt, render_system_user

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "P1_atomic_extract.txt"
LAW_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "P1_law_extract.txt"

# 三要素骨架字段：v1.2 起必填
_SKELETON_FIELDS = ("assumption", "behavior_mode", "consequence")

# 输出被 max_tokens 截断时的递归二分恢复：最多分 _MAX_SPLIT_DEPTH 层
# （一块 ~3000 字最多切成 2^4=16 片），低于 _MIN_SPLIT_CHARS 字则不再切、记终态失败。
_MAX_SPLIT_DEPTH = 4
_MIN_SPLIT_CHARS = 400

# 法规类来源走法条专用提示词
_LAW_SOURCE_TAGS = frozenset({"法规", "监管文件"})

# 颗粒度档位 → 每千字目标规则数区间（写进 prompt 并用于 under_extracted 校验）
GRANULARITY_DENSITY: dict[int, tuple[float, float]] = {
    1: (0.5, 1.0),
    2: (1.0, 2.0),
    3: (2.0, 4.0),
    4: (4.0, 6.0),
    5: (6.0, 10.0),
}


class P1BodyPipeline:
    pipeline_id = "P1"

    def __init__(self, router: LLMRouter, cfg: Config):
        self.router = router
        self.cfg = cfg
        self._prompt: PromptSections = load_prompt(PROMPT_PATH)
        self._law_prompt: PromptSections = load_prompt(LAW_PROMPT_PATH)

    def applicable(self, doc: ParsedDocument) -> bool:
        return not doc.is_passthrough and not doc.is_redline_doc

    async def extract(self, doc: ParsedDocument, ctx: dict) -> list[RuleCandidate]:
        sem = asyncio.Semaphore(self.cfg.concurrency.blocks)
        failed_blocks: list[ContentBlock] = []

        async def process_one(block: ContentBlock) -> list[RuleCandidate]:
            async with sem:
                progress = ctx.get("progress")
                # 协作式停止：已请求取消则跳过排队中的块（在途块自然跑完），保留已抽规则。
                if progress is not None and getattr(progress, "cancel_requested", False):
                    return []
                rules = await self._extract_block(
                    doc, block, ctx, failed_blocks=failed_blocks
                )
                progress = ctx.get("progress")
                if progress:
                    progress.mark_pipeline_block_done(
                        self.pipeline_id,
                        doc.filename,
                        len(rules),
                    )
                return rules

        block_results = await asyncio.gather(
            *[process_one(b) for b in doc.blocks]
        )

        all_rules: list[RuleCandidate] = []
        for block_rules in block_results:
            all_rules.extend(block_rules)

        # v1.2 泄漏修补：LLM 失败的块不再静默丢弃——主流程跑完后串行低速重试一轮
        if failed_blocks:
            all_rules.extend(await self._retry_failed_blocks(doc, ctx, failed_blocks))

        return all_rules

    async def _retry_failed_blocks(
        self, doc: ParsedDocument, ctx: dict, failed_blocks: list[ContentBlock]
    ) -> list[RuleCandidate]:
        recovered: list[RuleCandidate] = []
        progress = ctx.get("progress")
        for block in list(failed_blocks):
            await asyncio.sleep(1.0)
            try:
                rules = await self._extract_block(
                    doc, block, ctx, failed_blocks=None
                )
            except Exception as exc:  # noqa: BLE001 - 最终失败记审计
                record_llm_failure(ctx, self.pipeline_id, doc.filename, block.block_id, exc)
                continue
            recovered.extend(rules)
            if progress:
                progress.mark_pipeline_block_done(self.pipeline_id, doc.filename, len(rules))
        return recovered

    async def _extract_block(
        self,
        doc: ParsedDocument,
        block: ContentBlock,
        ctx: dict,
        failed_blocks: list[ContentBlock] | None = None,
        split_depth: int = 0,
    ) -> list[RuleCandidate]:
        system_prompt, user_prompt = self._render_prompt(doc, block, ctx)

        try:
            obj = await self.router.chat_json(
                system=system_prompt,
                user=user_prompt,
                temperature=0.2,
            )
        except LLMTruncatedError:
            # 输出被 max_tokens 截断：递归二分重切，直到每片输出能放下或块小到无法再切。
            if split_depth < _MAX_SPLIT_DEPTH and len(block.text) > _MIN_SPLIT_CHARS:
                return await self._extract_split_block(doc, block, ctx, split_depth + 1)
            record_llm_failure(
                ctx, self.pipeline_id, doc.filename, block.block_id,
                LLMTruncatedError("truncated and block too small to split"),
            )
            return []
        except Exception as exc:
            logger.exception("LLM call failed for block %s in %s", block.block_id, doc.filename)
            if failed_blocks is not None:
                failed_blocks.append(block)
            else:
                record_llm_failure(ctx, self.pipeline_id, doc.filename, block.block_id, exc)
            return []

        if obj.get("informational"):
            self._record_skipped(ctx, doc, block, str(obj.get("skip_reason") or ""))
            return []

        raw_rules = list(obj.get("rules", []))

        # v1.2 三要素骨架：缺要素的规则做一次定向补全（每块至多一次额外调用）
        incomplete = [r for r in raw_rules if _missing_skeleton(r)]
        if incomplete:
            raw_rules = await self._refine_three_elements(
                doc, block, raw_rules, incomplete
            )

        results: list[RuleCandidate] = []
        for rule in raw_rules:
            results.append(self._build_candidate(doc, block, rule))
        return results

    async def _extract_split_block(
        self, doc: ParsedDocument, block: ContentBlock, ctx: dict, split_depth: int
    ) -> list[RuleCandidate]:
        mid = len(block.text) // 2
        # 在中点附近找换行切，避免劈断句子
        split_at = block.text.find("\n", mid)
        if split_at == -1 or split_at > mid + 400:
            split_at = mid
        halves = [
            ContentBlock(
                block_id=f"{block.block_id}a",
                text=block.text[:split_at],
                location=block.location,
                block_type=block.block_type,
            ),
            ContentBlock(
                block_id=f"{block.block_id}b",
                text=block.text[split_at:],
                location=block.location,
                block_type=block.block_type,
            ),
        ]
        out: list[RuleCandidate] = []
        for half in halves:
            if half.text.strip():
                out.extend(await self._extract_block(
                    doc, half, ctx, failed_blocks=None, split_depth=split_depth
                ))
        return out

    async def _refine_three_elements(
        self,
        doc: ParsedDocument,
        block: ContentBlock,
        all_rules: list[dict],
        incomplete: list[dict],
    ) -> list[dict]:
        """对缺三要素的规则发一次定向补全调用；补不出来原样放行（由校验标记）。"""
        try:
            items = [
                {
                    "index": all_rules.index(r),
                    "check_item": r.get("check_item", ""),
                    "requirement": r.get("requirement", ""),
                    "assumption": r.get("assumption", ""),
                    "behavior_mode": r.get("behavior_mode", ""),
                    "consequence": r.get("consequence", ""),
                }
                for r in incomplete
            ]
            import json as _json

            obj = await self.router.chat_json(
                system=(
                    "你是法律规则三要素补全员。给定原文和若干缺少三要素的审查规则，"
                    "为每条规则补全 assumption（假定条件）/ behavior_mode（行为模式）/ "
                    "consequence（法律后果）。只依据原文；原文未规定后果时 consequence 写"
                    "'原文未规定后果；实务风险：…'。返回严格 JSON："
                    '{"items": [{"index": int, "assumption": str, "behavior_mode": str, "consequence": str}]}'
                ),
                user=f"【原文】\n{block.text}\n\n【待补全规则】\n{_json.dumps(items, ensure_ascii=False)}",
                temperature=0.1,
            )
            for item in obj.get("items", []):
                idx = item.get("index")
                if not isinstance(idx, int) or not (0 <= idx < len(all_rules)):
                    continue
                target = all_rules[idx]
                for field_name in _SKELETON_FIELDS:
                    if not str(target.get(field_name) or "").strip():
                        target[field_name] = str(item.get(field_name) or "")
        except Exception:
            logger.warning(
                "three-element refinement failed for %s:%s",
                doc.filename, block.block_id, exc_info=True,
            )
        return all_rules

    def _build_candidate(
        self, doc: ParsedDocument, block: ContentBlock, rule: dict
    ) -> RuleCandidate:
        # theme_key 就近映射到白名单；映射不上降级为 uncertainty 而非 struct fail
        raw_theme = str(rule.get("theme_key", ""))
        mapped_theme = map_theme_key(raw_theme)
        rule["theme_key"] = mapped_theme

        failures = validate_atomic(rule)
        theme_unmapped = mapped_theme not in THEME_KEYS
        if theme_unmapped and "theme_key_not_in_whitelist" in failures:
            failures.remove("theme_key_not_in_whitelist")

        # v1.2 三要素必填校验（补全后仍缺 → struct fail）
        for field_name in _SKELETON_FIELDS:
            if not str(rule.get(field_name) or "").strip():
                failures.append(f"{field_name}_missing")

        struct_ok = len(failures) == 0

        kws = rule.get("keywords", [])
        if isinstance(kws, str):
            kws = [k.strip() for k in kws.split(",") if k.strip()]

        uncertainty = rule.get("uncertainty_points", [])
        if isinstance(uncertainty, str):
            uncertainty = [u.strip() for u in uncertainty.split(";") if u.strip()]
        if theme_unmapped and raw_theme:
            uncertainty = list(uncertainty) + [f"theme_key未映射:{raw_theme}"]

        return RuleCandidate(
            risk_level=str(rule.get("risk_level", "中")),
            keywords=tuple(kws),
            check_item=str(rule.get("check_item", "")),
            requirement=str(rule.get("requirement", "")),
            notes=str(rule.get("notes", "")),
            rule_type=str(rule.get("rule_type", "clause")),
            theme_key=str(rule.get("theme_key", "")),
            subject=str(rule.get("subject", "")),
            predicate=str(rule.get("predicate", "")),
            threshold_type=str(rule.get("threshold_type", "无")),
            direction=str(rule.get("direction", "正向")),
            source_excerpt=block.text,
            source_location=block.location,
            pipeline=self.pipeline_id,
            self_confidence=float(rule.get("self_confidence", 0.5)),
            uncertainty_points=tuple(uncertainty),
            source_filename=doc.filename,
            source_sha256=doc.sha256,
            source_tag=doc.source_tag,
            priority=doc.priority,
            contract_types=tuple(doc.contract_types),
            model=self.router.primary.name if self.router.primary else "",
            struct_check_pass=struct_ok,
            struct_failures=tuple(failures),
            assumption=_string_field(rule, "assumption"),
            behavior_mode=_string_field(rule, "behavior_mode"),
            consequence=_string_field(rule, "consequence"),
            exception_conditions=_string_field(rule, "exception_conditions"),
            review_action=_string_field(rule, "review_action"),
            transformation_note=_string_field(rule, "transformation_note"),
        )

    def _record_skipped(
        self, ctx: dict, doc: ParsedDocument, block: ContentBlock, skip_reason: str
    ) -> None:
        progress = ctx.get("progress")
        if progress is None or not hasattr(progress, "skipped_blocks"):
            return
        progress.skipped_blocks.append({
            "filename": doc.filename,
            "location": block.location,
            "skip_reason": skip_reason or "（模型未给出理由）",
            "excerpt": block.text[:300],
        })

    def _render_prompt(
        self, doc: ParsedDocument, block: ContentBlock, ctx: dict
    ) -> tuple[str, str]:
        redline_text = ", ".join(self.cfg.extraction.redline_keywords) or "无"
        theme_keys_text = "\n".join(sorted(THEME_KEYS))
        industry_text = (
            ctx.get("industry_context")
            or self.cfg.extraction.industry_vocabulary
            or "无"
        )
        jurisdiction = ctx.get("jurisdiction", "中国大陆")
        contract_types_str = ", ".join(doc.contract_types) if doc.contract_types else "通用"

        is_law = doc.source_tag in _LAW_SOURCE_TAGS
        prompt = self._law_prompt if is_law else self._prompt

        return render_system_user(
            prompt,
            system_vars={
                "redline_keywords": redline_text,
                "theme_keys": theme_keys_text,
                "industry_context": industry_text,
                "coverage_policy": _coverage_policy(self.cfg, is_law=is_law),
                "task_guidance": _task_guidance(ctx),
                "document_profile": str(ctx.get("document_profile_text") or "无"),
            },
            user_vars={
                "filename": doc.filename,
                "source_tag": doc.source_tag,
                "priority": str(doc.priority),
                "contract_types": contract_types_str,
                "jurisdiction": jurisdiction,
                "location": block.location,
                "block_text": block.text,
                "task_mode_label": str(ctx.get("task_mode_label", "全量规则沉淀")),
                "our_party": str(ctx.get("our_party", "通用")),
                "scope_description": str(ctx.get("scope_description", "")) or "无",
            },
        )


def _missing_skeleton(rule: dict) -> bool:
    return any(not str(rule.get(f) or "").strip() for f in _SKELETON_FIELDS)


_GRANULARITY_POLICIES: dict[int, str] = {
    1: "当前颗粒度为 1（粗）：只抽取强义务条款和高风险禁止项；同主体同主题的相邻要求可合并为一条规则；RuleCount 可取 min(G,K)。",
    2: "当前颗粒度为 2（较粗）：抽取稳定、可复用的审查口径；同主体同主题可适度合并；明确独立的阈值和例外仍要单独成规则。",
    3: "当前颗粒度为 3（平衡）：优先抽取稳定、可复用的审查口径；同段内明确独立的条件、主体、阈值和例外必须拆分。",
    4: "当前颗粒度为 4（细）：以少漏审为优先。每个段落都要寻找可复用审查口径；同一段存在多个条件、主体、例外、证据点、风险后果时，必须拆成多条原子规则。",
    5: "当前颗粒度为 5（极细）：穷尽式拆解。RuleCount 严格取 max(G,M,K,D)；每个例外条件、每个列举项单独成规则；几乎不允许跳过段落。",
}


def _coverage_policy(cfg: Config, is_law: bool = False) -> str:
    level = getattr(cfg.extraction, "granularity_level", None) or (
        4 if cfg.extraction.granularity == "fine" else 3
    )
    level = max(1, min(5, int(level)))
    granularity = _GRANULARITY_POLICIES[level]
    low, high = GRANULARITY_DENSITY[level]
    if is_law:
        # 法条信息密度远高于合同（一条 50 字可含定义/义务/例外/后果多条规则）。
        # 按字数设上限会主动抑制穷尽拆条，对法规只保留下限、不设上限。
        density = (
            f"目标规则密度：每 1000 字原文至少 {low:g} 条规则，法条密度高，不设上限。"
            "本块若含多个条文，必须逐条独立处理、各自穷尽其全部规则"
            "（定义/义务/禁止/例外/法律后果/期限/程序），不要跨条归纳或合并；漏拆比过细更严重。"
        )
    else:
        density = (
            f"目标规则密度：每 1000 字原文约 {low:g}–{high:g} 条规则。"
            "明显低于下限说明你漏拆了；明显高于上限说明你过度碎片化。"
        )

    if cfg.extraction.regulation_depth == "full":
        depth = (
            "法规深度为 full：法规、裁判规则、证据规则、效力边界、成立要件、例外条件和审查建议均应规则化；"
            "不得因原文是解释性/分析性文字就跳过。"
        )
    else:
        depth = "法规深度为 limited：保留核心成立要件、禁止性规则和高风险例外。"

    skip_policy = (
        "- 跳过门槛：只能跳过纯背景、目录、事实经过、无可复用审查口径的内容，且必须给出 skip_reason。\n"
        if level <= 3
        else "- 跳过门槛（严格）：几乎不允许整块跳过；任何含规范性内容的片段都要转化为规则，跳过必须给出 skip_reason。\n"
    )

    return (
        f"{granularity}\n{density}\n{depth}\n"
        f"{skip_policy}"
        "- 若段落包含裁判摘要、法院认为、法律后果、举证责任、证据适用、合同效力、撤销/解除条件、登记/公示效力等内容，"
        "即使没有'应当/不得'，也要转化为 [条款]/[合规] 审查规则。\n"
        "- 对案例/法律分析文本，输出应围绕'以后审合同时要检查什么、避免什么、补什么证据'，不要只做案情总结。\n"
        "- 没有具体数值时不要编造阈值，threshold_type 使用 无/列表/参照，并在 notes 说明原文依据。"
    )


def _task_guidance(ctx: dict) -> str:
    mode = str(ctx.get("task_mode") or "full_library")
    our_party = str(ctx.get("our_party") or "通用")
    scope = str(ctx.get("scope_description") or "").strip()
    if mode == "template_focused":
        return (
            "当前任务是围绕本次模板抽取规则。优先输出与本次模板的交易结构、条款主题、义务主体、风险点直接相关的规则；"
            "与模板无关的通用制度性口径可以降低 self_confidence，并在 uncertainty_points 说明相关性不足。"
            f"用户补充范围：{scope or '无'}。"
        )
    if mode == "template_strategy":
        return (
            f"当前任务是从对方模板/资料中提炼对我方（{our_party}）有利或必须争取的规则。"
            "输出时优先识别：对我方有利条款、对我方不利需改写条款、必须补充条款、可谈判底线。"
            "requirement 应写成我方审查/起草时可采用的口径，不要直接照抄对方不利表述；"
            "notes 说明该规则对我方的价值、适用边界或谈判提示。"
            f"用户补充范围：{scope or '无'}。"
        )
    return "当前任务是全量规则沉淀，按来源文本完整抽取可复用审查规则。"


def _string_field(rule: dict, field_name: str) -> str:
    value = rule.get(field_name, "")
    return "" if value is None else str(value)
