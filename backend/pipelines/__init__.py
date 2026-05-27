"""Pipeline registry.

Order matters only for logging — runtime ordering is parallel via asyncio.gather.
"""
from __future__ import annotations

from .direct_passthrough import DirectPassthroughPipeline
from .p1_body import P1BodyPipeline
from .p2_comment import P2CommentPipeline
from .p3_revision import P3RevisionPipeline
from .p4_redline import P4RedlinePipeline
from .p5_case import P5CasePipeline

ALL_PIPELINES: list[type] = [
    DirectPassthroughPipeline,
    P1BodyPipeline,
    P2CommentPipeline,
    P3RevisionPipeline,
    P4RedlinePipeline,
    P5CasePipeline,
]
