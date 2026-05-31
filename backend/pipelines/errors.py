from __future__ import annotations


def record_llm_failure(
    ctx: dict,
    pipeline_id: str,
    filename: str,
    unit_id: str,
    exc: Exception,
) -> None:
    progress = ctx.get("progress")
    if progress is None or not hasattr(progress, "errors"):
        return

    detail = str(exc).replace("\n", " ").strip()
    if len(detail) > 300:
        detail = detail[:300] + "..."
    progress.errors.append(
        f"llm_failed:{pipeline_id}:{filename}:{unit_id}:{type(exc).__name__}:{detail}"
    )
