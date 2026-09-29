"""The placeholder classifier: every label is "unknown", and says why.

Never "normal": a stub that called everything normal would write confident
nonsense into every result — the failure that retired the greenhouse model
(docs/features/architecture.txt, crop-health predictions). Replaced by
Reagan's classifier (docs/handoffs/dpp-classify.txt).
"""

from __future__ import annotations

from cropwatcher.pipeline.contracts import (
    ClassifyResult,
    CleanResult,
    EnhanceResult,
    FlightContext,
    ImageVerdict,
    Label,
    PointData,
)

NO_MODEL = "no classifier yet"


class StubClassifier:
    name = "stub"
    version = "0"

    def classify(self, data: PointData, clean: CleanResult, enhanced: EnhanceResult,
                 ctx: FlightContext) -> ClassifyResult:
        model = f"{self.name}@{self.version}"
        return ClassifyResult(
            images=tuple(ImageVerdict(seq=f.seq, source="original",
                                      label=Label("unknown", None, model, NO_MODEL))
                         for f in data.frames),
            sensors=Label("unknown", None, model, NO_MODEL),
            features={},
        )
