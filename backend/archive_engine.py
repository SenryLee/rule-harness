"""File auto-archiving engine.

Classifies uploaded legal documents into a structured directory hierarchy,
using rule-based heuristics (document_profile + preview) as the primary
classifier, with optional LLM enhancement for low-confidence files.

Public API:
    classify_files()  — returns classification results without moving files
    execute_archive() — moves/copies files into the target directory structure
"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config, PROJECT_ROOT
from .document_profile import profile_document
from .llm import LLMRouter, create_llm_router
from .preview import extract_preview_text, preview_classify_text

logger = logging.getLogger(__name__)

ARCHIVE_ROOT = PROJECT_ROOT / "data" / "archived"

# ── Category hierarchy ─────────────────────────────────────────────
# Maps (document_type OR source_tag) → (top_dir, sub_dir)
# Falls back to "其他/未分类" when nothing matches.

_CATEGORY_MAP: dict[str, tuple[str, str]] = {
    # document_profile document_type mappings
    "国家法律":            ("法律法规", "国家法律"),
    "司法解释":            ("法律法规", "司法解释"),
    "部门规章/监管通知":   ("法律法规", "部门规章"),
    "地方红头文件":        ("法律法规", "地方文件"),
    "地方司法裁判指引":    ("裁判文书与案例", "司法指引"),
    "司法问答/解释性材料":  ("法律法规", "司法问答"),
    "已有规则CSV":         ("已有规则", "规则库"),
    "股权转让合同":        ("合同文本", "股权转让"),
    "合同文本":            ("合同文本", "通用合同"),
    # preview source_tag mappings (fallback)
    "法规":       ("法律法规", "综合"),
    "公司红线":   ("内部制度", "公司红线"),
    "内部制度":   ("内部制度", "管理制度"),
    "标准条款库": ("内部制度", "标准条款"),
    "合同模板":   ("合同文本", "模板"),
    "历史合同":   ("合同文本", "历史合同"),
    "业务规范":   ("内部制度", "业务规范"),
    "案例":       ("裁判文书与案例", "案例"),
    "审查清单":   ("已有规则", "审查清单"),
    "行业特殊":   ("行业资料", "特殊资料"),
}


@dataclass
class FileClassification:
    """Classification result for a single file."""
    original_name: str
    file_size: int
    # Rule-based results
    document_type: str
    authority_level: str
    primary_topic: str
    source_tag: str
    confidence: float
    evidence: list[str]
    # Archive target
    category_dir: str       # e.g. "法律法规/司法解释"
    target_filename: str    # cleaned filename
    # LLM enhancement (None if not run)
    llm_enhanced: bool = False
    llm_category: str | None = None
    llm_summary: str | None = None
    llm_confidence: float | None = None


@dataclass
class ArchiveResult:
    """Result of an archive operation."""
    archive_id: str
    timestamp: str
    total_files: int
    classified_files: list[FileClassification]
    directory_tree: dict[str, list[str]]   # category_dir → [filenames]
    high_confidence: int = 0
    low_confidence: int = 0


# ── Classification ──────────────────────────────────────────────────

def classify_files(
    file_paths: list[Path],
    file_contents: dict[str, bytes] | None = None,
) -> list[FileClassification]:
    """Classify files using rule-based heuristics. No LLM calls.

    Args:
        file_paths: paths to the uploaded files on disk
        file_contents: optional pre-read bytes keyed by filename
    """
    results: list[FileClassification] = []
    for path in file_paths:
        try:
            content = (file_contents or {}).get(path.name) or path.read_bytes()
            result = _classify_one(path.name, content, len(content))
            results.append(result)
        except Exception as exc:
            logger.exception("Failed to classify %s", path.name)
            results.append(_fallback_classification(path.name, 0, str(exc)))
    return results


def _classify_one(
    filename: str,
    content: bytes,
    file_size: int,
) -> FileClassification:
    """Rule-based classification for a single file."""
    text = extract_preview_text(filename, content, limit=3000)
    preview = preview_classify_text(filename, text)
    profile = preview.get("document_profile", {})

    doc_type = str(profile.get("document_type", ""))
    authority = str(profile.get("authority_level", ""))
    topic = str(profile.get("primary_legal_topic", ""))
    source_tag = str(preview.get("suggested_source_tag", "历史合同"))
    confidence = float(profile.get("confidence", 0.0))
    evidence = list(profile.get("evidence", []))

    # Resolve category: prefer document_type (more specific), fall back to source_tag
    category_dir = _resolve_category(doc_type, source_tag)
    target_name = _clean_filename(filename)

    return FileClassification(
        original_name=filename,
        file_size=file_size,
        document_type=doc_type or "未识别",
        authority_level=authority or "未识别",
        primary_topic=topic or "通用",
        source_tag=source_tag,
        confidence=confidence,
        evidence=evidence,
        category_dir=category_dir,
        target_filename=target_name,
    )


def _fallback_classification(filename: str, file_size: int, error: str) -> FileClassification:
    return FileClassification(
        original_name=filename,
        file_size=file_size,
        document_type="未识别",
        authority_level="未识别",
        primary_topic="通用",
        source_tag="历史合同",
        confidence=0.0,
        evidence=[f"分类失败: {error}"],
        category_dir="其他/未分类",
        target_filename=_clean_filename(filename),
    )


def _resolve_category(doc_type: str, source_tag: str) -> str:
    """Pick the best category directory from the hierarchy map."""
    if doc_type and doc_type in _CATEGORY_MAP:
        top, sub = _CATEGORY_MAP[doc_type]
        return f"{top}/{sub}"
    if source_tag and source_tag in _CATEGORY_MAP:
        top, sub = _CATEGORY_MAP[source_tag]
        return f"{top}/{sub}"
    return "其他/未分类"


def _clean_filename(filename: str) -> str:
    """Sanitize but preserve the original filename as much as possible."""
    # Remove leading numeric prefixes like "000_" added by batch upload
    import re
    cleaned = re.sub(r"^\d{2,4}_", "", filename)
    # Remove double spaces, trim
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or filename


# ── LLM Enhancement ────────────────────────────────────────────────

_LLM_CLASSIFY_SYSTEM = """你是一个法律文档分类专家。根据文件名和正文摘要，判断文件属于以下哪个类别：

可选类别：
- 法律法规/国家法律
- 法律法规/司法解释
- 法律法规/部门规章
- 法律法规/地方文件
- 法律法规/司法问答
- 裁判文书与案例/司法指引
- 裁判文书与案例/案例
- 合同文本/模板
- 合同文本/历史合同
- 合同文本/股权转让
- 合同文本/通用合同
- 内部制度/公司红线
- 内部制度/管理制度
- 内部制度/标准条款
- 内部制度/业务规范
- 已有规则/规则库
- 已有规则/审查清单
- 行业资料/特殊资料
- 其他/未分类

返回 JSON：
{
  "category": "选中的类别路径",
  "confidence": 0.0-1.0,
  "summary": "一句话说明文件内容",
  "reasoning": "分类依据"
}"""


async def enhance_with_llm(
    classifications: list[FileClassification],
    file_contents: dict[str, bytes],
    cfg: Config,
    confidence_threshold: float = 0.5,
) -> list[FileClassification]:
    """Use LLM to re-classify files whose rule-based confidence is below threshold."""
    router = create_llm_router(cfg)
    enhanced: list[FileClassification] = []

    for item in classifications:
        if item.confidence >= confidence_threshold:
            enhanced.append(item)
            continue

        content = file_contents.get(item.original_name, b"")
        text = extract_preview_text(item.original_name, content, limit=2000)
        user_msg = f"文件名: {item.original_name}\n\n正文摘要（前2000字）:\n{text[:2000]}"

        try:
            result = await router.chat_json(
                system=_LLM_CLASSIFY_SYSTEM,
                user=user_msg,
                temperature=0.1,
            )
            llm_cat = str(result.get("category", ""))
            llm_conf = float(result.get("confidence", 0.0))
            llm_summary = str(result.get("summary", ""))

            # Accept LLM result if it's more confident than rule-based
            if llm_conf > item.confidence and llm_cat:
                item.category_dir = llm_cat
                item.confidence = max(item.confidence, llm_conf * 0.85)
                item.evidence.append(f"LLM增强: {result.get('reasoning', '')}")

            item.llm_enhanced = True
            item.llm_category = llm_cat
            item.llm_summary = llm_summary
            item.llm_confidence = llm_conf
        except Exception as exc:
            logger.warning("LLM enhancement failed for %s: %s", item.original_name, exc)
            item.llm_enhanced = False

        enhanced.append(item)

    return enhanced


# ── Archive Execution ───────────────────────────────────────────────

def execute_archive(
    classifications: list[FileClassification],
    source_dir: Path,
    archive_id: str,
    archive_root: Path | None = None,
) -> ArchiveResult:
    """Copy files into the structured archive directory.

    Does NOT delete originals — always copies to preserve the source.
    """
    root = archive_root or ARCHIVE_ROOT
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    session_dir = root / f"{timestamp}_{archive_id}"
    session_dir.mkdir(parents=True, exist_ok=True)

    directory_tree: dict[str, list[str]] = {}
    high_conf = 0
    low_conf = 0

    for item in classifications:
        cat_dir = session_dir / item.category_dir
        cat_dir.mkdir(parents=True, exist_ok=True)

        src = source_dir / item.original_name
        dst = cat_dir / item.target_filename

        # Handle name collision
        if dst.exists():
            stem = dst.stem
            suffix = dst.suffix
            counter = 1
            while dst.exists():
                dst = cat_dir / f"{stem}_{counter}{suffix}"
                counter += 1

        if src.exists():
            shutil.copy2(str(src), str(dst))
        else:
            logger.warning("Source file not found: %s", src)

        category_key = item.category_dir
        directory_tree.setdefault(category_key, []).append(item.target_filename)

        if item.confidence >= 0.5:
            high_conf += 1
        else:
            low_conf += 1

    # Write metadata index
    _write_manifest(session_dir, classifications, archive_id, timestamp)

    return ArchiveResult(
        archive_id=archive_id,
        timestamp=timestamp,
        total_files=len(classifications),
        classified_files=classifications,
        directory_tree=directory_tree,
        high_confidence=high_conf,
        low_confidence=low_conf,
    )


def _write_manifest(
    session_dir: Path,
    items: list[FileClassification],
    archive_id: str,
    timestamp: str,
) -> None:
    """Write a JSON manifest with all classification metadata."""
    manifest = {
        "archive_id": archive_id,
        "timestamp": timestamp,
        "total_files": len(items),
        "files": [
            {
                "original_name": item.original_name,
                "target_path": f"{item.category_dir}/{item.target_filename}",
                "document_type": item.document_type,
                "authority_level": item.authority_level,
                "primary_topic": item.primary_topic,
                "source_tag": item.source_tag,
                "confidence": item.confidence,
                "evidence": item.evidence,
                "llm_enhanced": item.llm_enhanced,
                "llm_summary": item.llm_summary,
                "file_size": item.file_size,
            }
            for item in items
        ],
    }
    manifest_path = session_dir / "_归档清单.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── Serialization ──────────────────────────────────────────────────

def classification_to_dict(item: FileClassification) -> dict[str, Any]:
    return {
        "original_name": item.original_name,
        "file_size": item.file_size,
        "document_type": item.document_type,
        "authority_level": item.authority_level,
        "primary_topic": item.primary_topic,
        "source_tag": item.source_tag,
        "confidence": item.confidence,
        "evidence": item.evidence,
        "category_dir": item.category_dir,
        "target_filename": item.target_filename,
        "llm_enhanced": item.llm_enhanced,
        "llm_category": item.llm_category,
        "llm_summary": item.llm_summary,
        "llm_confidence": item.llm_confidence,
    }


def archive_result_to_dict(result: ArchiveResult) -> dict[str, Any]:
    return {
        "archive_id": result.archive_id,
        "timestamp": result.timestamp,
        "total_files": result.total_files,
        "high_confidence": result.high_confidence,
        "low_confidence": result.low_confidence,
        "directory_tree": result.directory_tree,
        "files": [classification_to_dict(f) for f in result.classified_files],
    }
