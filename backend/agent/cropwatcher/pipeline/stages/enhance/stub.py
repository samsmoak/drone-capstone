"""The placeholder enhancer: every frame passes through as it was taken.

path=None means "not enhanced — use the original", which is exactly true.
Replaced in the pipeline by clahe@1 (docs/handoffs/sprint-1/done/dpp-enhance.txt).
"""

from __future__ import annotations

from cropwatcher.pipeline.contracts import EnhancedFrame, EnhanceResult, FlightContext, PointData


class StubEnhancer:
    name = "stub"
    version = "0"

    def enhance(self, data: PointData, ctx: FlightContext) -> EnhanceResult:
        return EnhanceResult(frames=tuple(
            EnhancedFrame(frame=f, path=None, method="identity", scale=1,
                          note="no enhancer yet — the original frame is used")
            for f in data.frames))
