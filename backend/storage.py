from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB_PATH = _PROJECT_ROOT / "data" / "harness.sqlite"

_db_path: Path = _DEFAULT_DB_PATH
_lock = threading.Lock()


def get_db_path() -> Path:
    return _db_path


def set_db_path(path: Path) -> None:
    global _db_path
    _db_path = path


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def transaction() -> Generator[sqlite3.Connection, None, None]:
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_to_dataclass(row: sqlite3.Row, cls: type) -> Any:
    row_dict = dict(row)
    return cls(**row_dict)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RuleRecord:
    rule_id: str
    enabled: str = "启用"
    risk_level: str = "中"
    keywords: str = ""
    check_item: str = ""
    requirement: str = ""
    notes: str = ""
    fingerprint: str = ""
    first_batch_id: str = ""
    last_batch_id: str = ""
    version: int = 1
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)


@dataclass(frozen=True)
class RuleMetadataRecord:
    rule_id: str
    rule_type: str = "clause"
    applicable_contracts: str = ""
    jurisdiction: str = ""
    source_filename: str = ""
    source_sha256: str = ""
    source_location: str = ""
    source_excerpt: str = ""
    pipeline: str = ""
    model: str = ""
    self_confidence: float | None = None
    consistency_confidence: float | None = None
    struct_check_pass: bool = False
    conflict_flag: str = ""
    combined_confidence: float | None = None
    theme_key: str = ""
    ladder_preferred: str = ""
    ladder_acceptable: str = ""
    ladder_unacceptable: str = ""
    cited_cases: str = ""
    parent_rule_id: str = ""
    variant_versions: str = ""
    extracted_at: str = field(default_factory=_now_iso)


@dataclass(frozen=True)
class SourceDocRecord:
    sha256: str
    filename: str
    source_tag: str
    priority: int
    contract_type: str = ""
    batch_id: str = ""
    uploaded_at: str = field(default_factory=_now_iso)
    bytes: int | None = None
    parsed_chars: int | None = None


@dataclass(frozen=True)
class BatchRecord:
    batch_id: str
    started_at: str = ""
    finished_at: str = ""
    status: str = ""
    config_snapshot: str = ""
    stats: str = ""


@dataclass(frozen=True)
class MergeHistoryRecord:
    id: int = 0
    batch_id: str = ""
    rule_id: str = ""
    action: str = ""
    diff_payload: str = ""
    operated_at: str = field(default_factory=_now_iso)


def init_db() -> None:
    with transaction() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rules (
                rule_id        TEXT PRIMARY KEY,
                enabled        TEXT NOT NULL DEFAULT '启用',
                risk_level     TEXT NOT NULL,
                keywords       TEXT NOT NULL,
                check_item     TEXT NOT NULL,
                requirement    TEXT NOT NULL,
                notes          TEXT,
                fingerprint    TEXT NOT NULL,
                first_batch_id TEXT NOT NULL,
                last_batch_id  TEXT NOT NULL,
                version        INTEGER NOT NULL DEFAULT 1,
                created_at     TIMESTAMP NOT NULL,
                updated_at     TIMESTAMP NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rules_fingerprint ON rules(fingerprint)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rules_batch ON rules(last_batch_id)"
        )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS rule_metadata (
                rule_id              TEXT PRIMARY KEY REFERENCES rules(rule_id),
                rule_type            TEXT NOT NULL,
                applicable_contracts TEXT,
                jurisdiction         TEXT,
                source_filename      TEXT NOT NULL,
                source_sha256        TEXT NOT NULL,
                source_location      TEXT,
                source_excerpt       TEXT,
                pipeline             TEXT NOT NULL,
                model                TEXT NOT NULL,
                self_confidence      REAL,
                consistency_confidence REAL,
                struct_check_pass    INTEGER,
                conflict_flag        TEXT,
                combined_confidence  REAL,
                theme_key            TEXT NOT NULL,
                ladder_preferred     TEXT,
                ladder_acceptable    TEXT,
                ladder_unacceptable  TEXT,
                cited_cases          TEXT,
                parent_rule_id       TEXT,
                variant_versions     TEXT,
                extracted_at         TIMESTAMP
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_metadata_theme ON rule_metadata(theme_key)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_metadata_contract ON rule_metadata(applicable_contracts)"
        )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS source_documents (
                sha256        TEXT PRIMARY KEY,
                filename      TEXT NOT NULL,
                source_tag    TEXT NOT NULL,
                priority      INTEGER NOT NULL,
                contract_type TEXT,
                batch_id      TEXT NOT NULL,
                uploaded_at   TIMESTAMP NOT NULL,
                bytes         INTEGER,
                parsed_chars  INTEGER
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_source_tag ON source_documents(source_tag)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_source_batch ON source_documents(batch_id)"
        )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS batches (
                batch_id     TEXT PRIMARY KEY,
                started_at   TIMESTAMP,
                finished_at  TIMESTAMP,
                status       TEXT,
                config_snapshot TEXT,
                stats        TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS merge_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id     TEXT NOT NULL,
                rule_id      TEXT NOT NULL,
                action       TEXT NOT NULL,
                diff_payload TEXT,
                operated_at  TIMESTAMP
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_merge_batch ON merge_history(batch_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_merge_rule ON merge_history(rule_id)"
        )


def _scalar(query: str, params: tuple = ()) -> Any:
    with _lock:
        conn = _get_conn()
        try:
            row = conn.execute(query, params).fetchone()
            return row[0] if row else None
        finally:
            conn.close()


def find_rule_by_fingerprint(fp: str) -> RuleRecord | None:
    with _lock:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM rules WHERE fingerprint = ?", (fp,)
            ).fetchone()
            return _row_to_dataclass(row, RuleRecord) if row else None
        finally:
            conn.close()


def find_rule_by_id(rule_id: str) -> RuleRecord | None:
    with _lock:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM rules WHERE rule_id = ?", (rule_id,)
            ).fetchone()
            return _row_to_dataclass(row, RuleRecord) if row else None
        finally:
            conn.close()


def _keywords_to_str(keywords: list[str] | str) -> str:
    if isinstance(keywords, list):
        return ",".join(keywords)
    return keywords


def insert_rule(rule: dict, batch_id: str) -> RuleRecord:
    now = _now_iso()
    keywords = _keywords_to_str(rule.get("keywords", ""))
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO rules (rule_id, enabled, risk_level, keywords,
                               check_item, requirement, notes, fingerprint,
                               first_batch_id, last_batch_id, version,
                               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rule["rule_id"],
                rule.get("enabled", "启用"),
                rule.get("risk_level", "中"),
                keywords,
                rule.get("check_item", ""),
                rule.get("requirement", ""),
                rule.get("notes", ""),
                rule.get("fingerprint", ""),
                batch_id,
                batch_id,
                1,
                now,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM rules WHERE rule_id = ?", (rule["rule_id"],)
        ).fetchone()
    return _row_to_dataclass(row, RuleRecord)


def insert_rule_metadata(meta: dict) -> RuleMetadataRecord:
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO rule_metadata
            (rule_id, rule_type, applicable_contracts, jurisdiction,
             source_filename, source_sha256, source_location, source_excerpt,
             pipeline, model, self_confidence, consistency_confidence,
             struct_check_pass, conflict_flag, combined_confidence,
             theme_key, ladder_preferred, ladder_acceptable,
             ladder_unacceptable, cited_cases, parent_rule_id,
             variant_versions, extracted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                meta["rule_id"],
                meta.get("rule_type", "clause"),
                meta.get("applicable_contracts", ""),
                meta.get("jurisdiction", ""),
                meta.get("source_filename", ""),
                meta.get("source_sha256", ""),
                meta.get("source_location", ""),
                meta.get("source_excerpt", ""),
                meta.get("pipeline", ""),
                meta.get("model", ""),
                meta.get("self_confidence"),
                meta.get("consistency_confidence"),
                int(meta.get("struct_check_pass", False)),
                meta.get("conflict_flag", ""),
                meta.get("combined_confidence"),
                meta.get("theme_key", ""),
                meta.get("ladder_preferred", ""),
                meta.get("ladder_acceptable", ""),
                meta.get("ladder_unacceptable", ""),
                meta.get("cited_cases", ""),
                meta.get("parent_rule_id", ""),
                meta.get("variant_versions", ""),
                meta.get("extracted_at", _now_iso()),
            ),
        )
        row = conn.execute(
            "SELECT * FROM rule_metadata WHERE rule_id = ?", (meta["rule_id"],)
        ).fetchone()
    return _row_to_dataclass(row, RuleMetadataRecord)


def update_rule(rule_id: str, rule: dict, batch_id: str) -> RuleRecord:
    now = _now_iso()
    keywords = _keywords_to_str(rule.get("keywords", ""))
    with transaction() as conn:
        existing = conn.execute(
            "SELECT * FROM rules WHERE rule_id = ?", (rule_id,)
        ).fetchone()
        if not existing:
            raise ValueError(f"Rule {rule_id} not found")
        new_version = existing["version"] + 1
        conn.execute(
            """
            UPDATE rules SET
                enabled = ?, risk_level = ?, keywords = ?,
                check_item = ?, requirement = ?, notes = ?,
                last_batch_id = ?, version = ?, updated_at = ?
            WHERE rule_id = ?
            """,
            (
                rule.get("enabled", existing["enabled"]),
                rule.get("risk_level", existing["risk_level"]),
                keywords,
                rule.get("check_item", existing["check_item"]),
                rule.get("requirement", existing["requirement"]),
                rule.get("notes", existing["notes"]),
                batch_id,
                new_version,
                now,
                rule_id,
            ),
        )
        row = conn.execute(
            "SELECT * FROM rules WHERE rule_id = ?", (rule_id,)
        ).fetchone()
    return _row_to_dataclass(row, RuleRecord)


def append_variant(rule_id: str, variant: dict) -> RuleMetadataRecord:
    with transaction() as conn:
        existing = conn.execute(
            "SELECT * FROM rule_metadata WHERE rule_id = ?", (rule_id,)
        ).fetchone()
        if not existing:
            raise ValueError(f"Rule metadata for {rule_id} not found")

        current_variants = existing["variant_versions"] or "[]"
        variants_list = json.loads(current_variants)
        variants_list.append(variant)
        new_variants = json.dumps(variants_list, ensure_ascii=False)

        conn.execute(
            "UPDATE rule_metadata SET variant_versions = ? WHERE rule_id = ?",
            (new_variants, rule_id),
        )
        row = conn.execute(
            "SELECT * FROM rule_metadata WHERE rule_id = ?", (rule_id,)
        ).fetchone()
    return _row_to_dataclass(row, RuleMetadataRecord)


def log_conflict(rule_id: str, rule: dict, batch_id: str) -> RuleRecord:
    notes = rule.get("notes", "")
    conflict_note = f"[CONFLICT] {notes}".strip()
    updated_rule = dict(rule, notes=conflict_note)
    return update_rule(rule_id, updated_rule, batch_id)


def log_merge_history(batch_id: str, decision: dict) -> MergeHistoryRecord:
    now = _now_iso()
    diff_str = json.dumps(decision.get("diff_payload"), ensure_ascii=False) if decision.get("diff_payload") else ""
    with transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO merge_history (batch_id, rule_id, action, diff_payload, operated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                decision.get("rule_id", ""),
                decision.get("action", "skip"),
                diff_str,
                decision.get("operated_at", now),
            ),
        )
        row = conn.execute(
            "SELECT * FROM merge_history WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return _row_to_dataclass(row, MergeHistoryRecord)


def list_rules(
    enabled: str | None = None,
    risk_level: str | None = None,
    batch_id: str | None = None,
    fingerprint: str | None = None,
    limit: int = 1000,
    offset: int = 0,
) -> list[RuleRecord]:
    clauses: list[str] = []
    params: list[Any] = []

    if enabled is not None:
        clauses.append("enabled = ?")
        params.append(enabled)
    if risk_level is not None:
        clauses.append("risk_level = ?")
        params.append(risk_level)
    if batch_id is not None:
        clauses.append("last_batch_id = ?")
        params.append(batch_id)
    if fingerprint is not None:
        clauses.append("fingerprint = ?")
        params.append(fingerprint)

    where = " AND ".join(clauses) if clauses else "1=1"
    query = f"SELECT * FROM rules WHERE {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with _lock:
        conn = _get_conn()
        try:
            rows = conn.execute(query, tuple(params)).fetchall()
            return [_row_to_dataclass(r, RuleRecord) for r in rows]
        finally:
            conn.close()


def get_rule(rule_id: str) -> RuleRecord | None:
    return find_rule_by_id(rule_id)


def get_rule_metadata(rule_id: str) -> RuleMetadataRecord | None:
    with _lock:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM rule_metadata WHERE rule_id = ?", (rule_id,)
            ).fetchone()
            return _row_to_dataclass(row, RuleMetadataRecord) if row else None
        finally:
            conn.close()


def get_batch(batch_id: str) -> BatchRecord | None:
    with _lock:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            return _row_to_dataclass(row, BatchRecord) if row else None
        finally:
            conn.close()


def list_batches(limit: int = 100) -> list[BatchRecord]:
    with _lock:
        conn = _get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM batches ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [_row_to_dataclass(r, BatchRecord) for r in rows]
        finally:
            conn.close()


def insert_batch(batch: dict) -> BatchRecord:
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO batches (batch_id, started_at, finished_at, status,
                                 config_snapshot, stats)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                batch["batch_id"],
                batch.get("started_at", _now_iso()),
                batch.get("finished_at", ""),
                batch.get("status", "running"),
                batch.get("config_snapshot", "{}"),
                batch.get("stats", "{}"),
            ),
        )
        row = conn.execute(
            "SELECT * FROM batches WHERE batch_id = ?", (batch["batch_id"],)
        ).fetchone()
    return _row_to_dataclass(row, BatchRecord)


def update_batch(batch_id: str, updates: dict) -> BatchRecord:
    with transaction() as conn:
        existing = conn.execute(
            "SELECT * FROM batches WHERE batch_id = ?", (batch_id,)
        ).fetchone()
        if not existing:
            raise ValueError(f"Batch {batch_id} not found")
        conn.execute(
            """
            UPDATE batches SET
                finished_at = ?, status = ?, stats = ?
            WHERE batch_id = ?
            """,
            (
                updates.get("finished_at", existing["finished_at"]),
                updates.get("status", existing["status"]),
                updates.get("stats", existing["stats"]),
                batch_id,
            ),
        )
        row = conn.execute(
            "SELECT * FROM batches WHERE batch_id = ?", (batch_id,)
        ).fetchone()
    return _row_to_dataclass(row, BatchRecord)


def insert_source_document(doc: dict) -> SourceDocRecord:
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO source_documents
            (sha256, filename, source_tag, priority, contract_type,
             batch_id, uploaded_at, bytes, parsed_chars)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc["sha256"],
                doc["filename"],
                doc["source_tag"],
                doc["priority"],
                doc.get("contract_type", ""),
                doc["batch_id"],
                doc.get("uploaded_at", _now_iso()),
                doc.get("bytes"),
                doc.get("parsed_chars"),
            ),
        )
        row = conn.execute(
            "SELECT * FROM source_documents WHERE sha256 = ?", (doc["sha256"],)
        ).fetchone()
    return _row_to_dataclass(row, SourceDocRecord)


def find_source_by_sha256(sha256: str) -> SourceDocRecord | None:
    with _lock:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM source_documents WHERE sha256 = ?", (sha256,)
            ).fetchone()
            return _row_to_dataclass(row, SourceDocRecord) if row else None
        finally:
            conn.close()


def list_source_documents(batch_id: str | None = None) -> list[SourceDocRecord]:
    with _lock:
        conn = _get_conn()
        try:
            if batch_id:
                rows = conn.execute(
                    "SELECT * FROM source_documents WHERE batch_id = ? ORDER BY uploaded_at",
                    (batch_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM source_documents ORDER BY uploaded_at"
                ).fetchall()
            return [_row_to_dataclass(r, SourceDocRecord) for r in rows]
        finally:
            conn.close()


def list_merge_history(batch_id: str | None = None) -> list[MergeHistoryRecord]:
    with _lock:
        conn = _get_conn()
        try:
            if batch_id:
                rows = conn.execute(
                    "SELECT * FROM merge_history WHERE batch_id = ? ORDER BY operated_at",
                    (batch_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM merge_history ORDER BY operated_at"
                ).fetchall()
            return [_row_to_dataclass(r, MergeHistoryRecord) for r in rows]
        finally:
            conn.close()


def rule_count() -> int:
    return _scalar("SELECT COUNT(*) FROM rules") or 0


def batch_count() -> int:
    return _scalar("SELECT COUNT(*) FROM batches") or 0


def delete_rule(rule_id: str) -> bool:
    with transaction() as conn:
        conn.execute("DELETE FROM rule_metadata WHERE rule_id = ?", (rule_id,))
        cursor = conn.execute("DELETE FROM rules WHERE rule_id = ?", (rule_id,))
    return cursor.rowcount > 0
