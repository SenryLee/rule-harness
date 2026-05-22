from __future__ import annotations

from .p1_body import P1BodyPipeline
from .p5_case import P5CasePipeline
from .direct_passthrough import DirectPassthroughPipeline

ALL_PIPELINES: list[type] = [
    P1BodyPipeline,
    P5CasePipeline,
    DirectPassthroughPipeline,
]
