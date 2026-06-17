from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.default.yaml"
# 所有运行期数据（SQLite/上传/导出/归档）的根目录。默认 PROJECT_ROOT/data；
# 部署时把宿主机持久卷挂到容器内的该路径（默认 /app/data），重建容器数据就不再清零。
# 可用环境变量 DATA_DIR 覆盖（指向挂载点）。
DATA_DIR = Path(os.environ.get("DATA_DIR") or (PROJECT_ROOT / "data"))
USER_CONFIG_DIR = DATA_DIR
USER_CONFIG_PATH = USER_CONFIG_DIR / "config.yaml"


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    api_key: str
    base_url: str
    model: str
    rpm_limit: int
    tpm_limit: int


@dataclass(frozen=True)
class ModelsConfig:
    primary: ModelConfig
    fallback: ModelConfig


@dataclass(frozen=True)
class ExtractionConfig:
    granularity: str
    regulation_depth: str
    consistency_sampling: bool
    industry_preset: Optional[str]
    industry_vocabulary: str
    industry_focus_points: str
    redline_keywords: tuple[str, ...]
    # v1.2：颗粒度档位 1(粗)–5(极细)。旧 granularity 字符串保留兼容：
    # fine→4，balanced→3。档位同时驱动切块大小/拆分策略/跳过门槛/去重/密度提示。
    granularity_level: int = 3
    # v2.0: 即使 consistency_sampling=false，也仅对 risk_level=高 的规则做双采样
    consistency_sampling_high_risk_only: bool = True
    # v1.4 细化旋钮：None = 跟随档位联动；设置后单项覆盖
    chunk_chars: Optional[int] = None          # 目标切块字符数 600–4000
    density_min: Optional[float] = None        # 每千字最少规则数
    density_max: Optional[float] = None        # 每千字最多规则数（法规不设上限）
    skip_strictness: Optional[str] = None      # lenient(宽松跳过) | strict(几乎不跳)
    dedupe_level: Optional[int] = None         # 去重粒度 1(激进合并)–5(保守保留)
    # 合同抽取优化开关（默认开启，可单项关闭回退旧行为）
    template_first: bool = True                # 范本主导+历史降权（去重/合并主条排序）
    contract_semantic_dedupe: bool = True      # 合同来源按口径级语义去重（忽略 check_item 字面）
    genericize_instances: bool = True          # 对历史合同实例规则做 LLM 通用化重写


@dataclass(frozen=True)
class PriorityWeights:
    法规: int
    公司红线: int
    内部制度: int
    标准条款库: int
    历史合同: int


@dataclass(frozen=True)
class PriorityConfig:
    weights: PriorityWeights


@dataclass(frozen=True)
class ConfidenceWeights:
    self_: float = field(metadata={"yaml_key": "self"})
    consistency: float
    struct: float
    conflict: float
    fidelity: float = 0.25  # v1.1: 第五重门权重；v2.0 调整为 0.25
    semantic: float = 0.15  # v2.0: 语义忠实度门权重


@dataclass(frozen=True)
class ConfidenceConfig:
    threshold_review: float
    weights: ConfidenceWeights


@dataclass(frozen=True)
class ConcurrencyConfig:
    files: int
    blocks: int


@dataclass(frozen=True)
class OcrConfig:
    enabled: bool
    engine: str
    language: str


@dataclass(frozen=True)
class BudgetConfig:
    max_tokens_per_batch: int
    pause_on_overrun: bool


@dataclass(frozen=True)
class StorageConfig:
    db_path: str
    exports_dir: str


@dataclass(frozen=True)
class Config:
    models: ModelsConfig
    extraction: ExtractionConfig
    priorities: PriorityConfig
    confidence: ConfidenceConfig
    concurrency: ConcurrencyConfig
    ocr: OcrConfig
    budget: BudgetConfig
    storage: StorageConfig


def _ensure_user_config() -> None:
    if not USER_CONFIG_PATH.exists():
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        default_content = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
        USER_CONFIG_PATH.write_text(default_content, encoding="utf-8")


def _parse_model(raw: dict) -> ModelConfig:
    # 兼容 fallback 未配置时 provider: null 的 YAML 写法
    return ModelConfig(
        provider=raw.get("provider") or "",
        # config.yaml 留空时回退到环境变量，使密钥独立于配置文件：
        # 容器重建、config.yaml 被重置或被前端误清空时 key 仍在。
        api_key=(
            raw.get("api_key")
            or os.environ.get("RULE_HARNESS_API_KEY")
            or os.environ.get("DASHSCOPE_API_KEY")
            or ""
        ),
        base_url=raw.get("base_url") or "",
        model=raw.get("model") or "",
        rpm_limit=int(raw.get("rpm_limit") or 60),
        tpm_limit=int(raw.get("tpm_limit") or 200_000),
    )


def _parse_extraction(raw: dict) -> ExtractionConfig:
    legacy = raw.get("granularity", "balanced")
    try:
        level = int(raw.get("granularity_level") or (4 if legacy == "fine" else 3))
    except (TypeError, ValueError):
        level = 4 if legacy == "fine" else 3
    level = max(1, min(5, level))
    return ExtractionConfig(
        granularity="fine" if level >= 4 else "balanced",
        regulation_depth=raw["regulation_depth"],
        consistency_sampling=raw["consistency_sampling"],
        consistency_sampling_high_risk_only=raw.get("consistency_sampling_high_risk_only", True),
        industry_preset=raw.get("industry_preset"),
        industry_vocabulary=raw.get("industry_vocabulary", ""),
        industry_focus_points=raw.get("industry_focus_points", ""),
        redline_keywords=tuple(raw.get("redline_keywords", [])),
        granularity_level=level,
        chunk_chars=_opt_int(raw.get("chunk_chars"), 600, 4000),
        density_min=_opt_float(raw.get("density_min"), 0.1, 20.0),
        density_max=_opt_float(raw.get("density_max"), 0.1, 30.0),
        skip_strictness=(raw.get("skip_strictness")
                         if raw.get("skip_strictness") in ("lenient", "strict") else None),
        dedupe_level=_opt_int(raw.get("dedupe_level"), 1, 5),
        template_first=_opt_bool(raw.get("template_first"), True),
        contract_semantic_dedupe=_opt_bool(raw.get("contract_semantic_dedupe"), True),
        genericize_instances=_opt_bool(raw.get("genericize_instances"), True),
    )


def _opt_int(value, lo: int, hi: int) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return None


def _opt_float(value, lo: float, hi: float) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return None


def _opt_bool(value, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "是")
    return bool(value)


def _parse_priorities(raw: dict) -> PriorityConfig:
    return PriorityConfig(
        weights=PriorityWeights(**raw["weights"]),
    )


def _parse_confidence(raw: dict) -> ConfidenceConfig:
    weights_raw = raw["weights"]
    return ConfidenceConfig(
        threshold_review=raw["threshold_review"],
        weights=ConfidenceWeights(
            self_=float(weights_raw.get("self", 0.25)),
            consistency=float(weights_raw.get("consistency", 0.25)),
            struct=float(weights_raw.get("struct", 0.15)),
            conflict=float(weights_raw.get("conflict", 0.05)),
            fidelity=float(weights_raw.get("fidelity", 0.25)),
            semantic=float(weights_raw.get("semantic", 0.15)),
        ),
    )


def _parse_concurrency(raw: dict) -> ConcurrencyConfig:
    return ConcurrencyConfig(
        files=raw["files"],
        blocks=raw["blocks"],
    )


def _parse_ocr(raw: dict) -> OcrConfig:
    return OcrConfig(
        enabled=raw["enabled"],
        engine=raw["engine"],
        language=raw["language"],
    )


def _parse_budget(raw: dict) -> BudgetConfig:
    return BudgetConfig(
        max_tokens_per_batch=raw["max_tokens_per_batch"],
        pause_on_overrun=raw["pause_on_overrun"],
    )


def _parse_storage(raw: dict) -> StorageConfig:
    return StorageConfig(
        db_path=raw["db_path"],
        exports_dir=raw["exports_dir"],
    )


def _parse_config(raw: dict) -> Config:
    return Config(
        models=ModelsConfig(
            primary=_parse_model(raw["models"]["primary"]),
            fallback=_parse_model(raw["models"]["fallback"]),
        ),
        extraction=_parse_extraction(raw["extraction"]),
        priorities=_parse_priorities(raw["priorities"]),
        confidence=_parse_confidence(raw["confidence"]),
        concurrency=_parse_concurrency(raw["concurrency"]),
        ocr=_parse_ocr(raw["ocr"]),
        budget=_parse_budget(raw["budget"]),
        storage=_parse_storage(raw["storage"]),
    )


def load_config() -> Config:
    _ensure_user_config()
    raw = yaml.safe_load(USER_CONFIG_PATH.read_text(encoding="utf-8"))
    return _parse_config(raw)


def _model_to_dict(model: ModelConfig) -> dict:
    return {
        "provider": model.provider,
        "api_key": model.api_key,
        "base_url": model.base_url,
        "model": model.model,
        "rpm_limit": model.rpm_limit,
        "tpm_limit": model.tpm_limit,
    }


def _extraction_to_dict(extraction: ExtractionConfig) -> dict:
    return {
        "granularity": extraction.granularity,
        "granularity_level": extraction.granularity_level,
        "regulation_depth": extraction.regulation_depth,
        "consistency_sampling": extraction.consistency_sampling,
        "consistency_sampling_high_risk_only": extraction.consistency_sampling_high_risk_only,
        "industry_preset": extraction.industry_preset,
        "industry_vocabulary": extraction.industry_vocabulary,
        "industry_focus_points": extraction.industry_focus_points,
        "redline_keywords": list(extraction.redline_keywords),
        "chunk_chars": extraction.chunk_chars,
        "density_min": extraction.density_min,
        "density_max": extraction.density_max,
        "skip_strictness": extraction.skip_strictness,
        "dedupe_level": extraction.dedupe_level,
        "template_first": extraction.template_first,
        "contract_semantic_dedupe": extraction.contract_semantic_dedupe,
        "genericize_instances": extraction.genericize_instances,
    }


def config_to_dict(cfg: Config) -> dict:
    return {
        "models": {
            "primary": _model_to_dict(cfg.models.primary),
            "fallback": _model_to_dict(cfg.models.fallback),
        },
        "extraction": _extraction_to_dict(cfg.extraction),
        "priorities": {
            "weights": {
                "法规": cfg.priorities.weights.法规,
                "公司红线": cfg.priorities.weights.公司红线,
                "内部制度": cfg.priorities.weights.内部制度,
                "标准条款库": cfg.priorities.weights.标准条款库,
                "历史合同": cfg.priorities.weights.历史合同,
            },
        },
        "confidence": {
            "threshold_review": cfg.confidence.threshold_review,
            "weights": {
                "self": cfg.confidence.weights.self_,
                "consistency": cfg.confidence.weights.consistency,
                "struct": cfg.confidence.weights.struct,
                "conflict": cfg.confidence.weights.conflict,
                "fidelity": cfg.confidence.weights.fidelity,
                "semantic": cfg.confidence.weights.semantic,
            },
        },
        "concurrency": {
            "files": cfg.concurrency.files,
            "blocks": cfg.concurrency.blocks,
        },
        "ocr": {
            "enabled": cfg.ocr.enabled,
            "engine": cfg.ocr.engine,
            "language": cfg.ocr.language,
        },
        "budget": {
            "max_tokens_per_batch": cfg.budget.max_tokens_per_batch,
            "pause_on_overrun": cfg.budget.pause_on_overrun,
        },
        "storage": {
            "db_path": cfg.storage.db_path,
            "exports_dir": cfg.storage.exports_dir,
        },
    }


def save_config(cfg: Config) -> None:
    raw = config_to_dict(cfg)
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    USER_CONFIG_PATH.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
