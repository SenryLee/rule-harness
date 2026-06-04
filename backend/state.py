"""Shared in-memory state for batch lifecycle.

All mutable per-process caches live here so that route modules and the
orchestrator callback can import them from a single place.

SQLite (via :mod:`backend.storage`) is the persistent source of truth for rules;
the dicts below only hold data for the current process lifetime.
"""
from __future__ import annotations

from pathlib import Path

from .orchestrator import BatchProgress, BatchResult

# batch_id → batch metadata dict
batches: dict[str, dict] = {}

# batch_id → serialised rule list (API-ready dicts)
batch_rules: dict[str, list[dict]] = {}

# batch_id → serialised merge decisions
batch_decisions: dict[str, list[dict]] = {}

# batch_id → live progress object
batch_progress: dict[str, BatchProgress] = {}

# batch_id → {export_key: Path}
batch_exports: dict[str, dict[str, Path]] = {}
