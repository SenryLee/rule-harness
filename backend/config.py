from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.default.yaml"
USER_CONFIG_DIR = PROJECT_ROOT / "data"
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
    fidelity: float = 0.30  # v1.1: 第五重门权重；默认 0.30


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
        api_key=raw.get("api_key") or "",
        base_url=raw.get("base_url") or "",
        model=raw.get("model") or "",
        rpm_limit=int(raw.get("rpm_limit") or 60),
        tpm_limit=int(raw.get("tpm_limit") or 200_000),
    )


def _parse_extraction(raw: dict) -> ExtractionConfig:
    return ExtractionConfig(
        granularity=raw["granularity"],
        regulation_depth=raw["regulation_depth"],
        consistency_sampling=raw["consistency_sampling"],
        industry_preset=raw.get("industry_preset"),
        industry_vocabulary=raw.get("industry_vocabulary", ""),
        industry_focus_points=raw.get("industry_focus_points", ""),
        redline_keywords=tuple(raw.get("redline_keywords", [])),
    )


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
            fidelity=float(weights_raw.get("fidelity", 0.30)),
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
        "regulation_depth": extraction.regulation_depth,
        "consistency_sampling": extraction.consistency_sampling,
        "industry_preset": extraction.industry_preset,
        "industry_vocabulary": extraction.industry_vocabulary,
        "industry_focus_points": extraction.industry_focus_points,
        "redline_keywords": list(extraction.redline_keywords),
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
