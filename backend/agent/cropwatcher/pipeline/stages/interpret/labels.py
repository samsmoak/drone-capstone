"""Interpret: the classifier's labels → a verdict per inspection point.

THIS HOLDS NO TEMPERATURE OR PRESSURE THRESHOLD, and that is deliberate. A
"normal operating" limit is measured on the equipment (story 4.6: "define
normal thresholds"), never guessed — CLAUDE.md, flight invariant 1, and the
3.70 V threshold that refused good flights. The verdict rests on the
classifier alone:

    no usable readings and no frames      insufficient_data
    every label "unknown"                 insufficient_data — and why
    any label "faulty"                    anomaly, with an alert quoting the
                                          evidence (reading indexes, frames)
    otherwise                             normal

Contract v2: it is handed the whole flight and gives each inspection point its
verdict from the readings and frames stamped with that point. It makes no
findings — the finding interpreter does (stages/interpret/findings.py).
"""

from __future__ import annotations

from cropwatcher.pipeline.contracts import (
    Alert,
    ClassifyResult,
    CleanResult,
    EnhanceResult,
    FlightContext,
    InspectionPoint,
    InterpretResult,
    PointData,
    PointResult,
)


class LabelInterpreter:
    name = "labels"
    version = "2"

    def interpret(self, data: PointData, clean: CleanResult, enhanced: EnhanceResult,
                  classified: ClassifyResult, ctx: FlightContext) -> InterpretResult:
        points = ctx.points or (data.point,)
        return InterpretResult(tuple(self._point(p, data, clean, classified, whole=not ctx.points)
                                     for p in points))

    @staticmethod
    def _point(point: InspectionPoint, data: PointData, clean: CleanResult,
               classified: ClassifyResult, *, whole: bool) -> PointResult:
        def mine(point_id: str | None) -> bool:
            return whole or point_id == point.id

        readings = [r for r in clean.readings if mine(r.point_id)]
        frames = {f.seq for f in data.frames if mine(f.point_id)}
        usable = [r for r in readings if any(clean.usable(r.index, c) for c in r.values)]
        if not usable and not frames:
            return PointResult(point.id, "insufficient_data",
                               ("No usable readings and no frames at this point.",))

        images = [v for v in classified.images if v.seq in frames]
        faulty_frames = tuple(v.seq for v in images if v.label.value == "faulty")
        sensors_faulty = classified.sensors.value == "faulty" and bool(usable)
        if faulty_frames or sensors_faulty:
            reasons: list[str] = []
            alerts: list[Alert] = []
            if sensors_faulty:
                shown = ", ".join(f"{k} {v:.2f}" for k, v in classified.features.items())
                reason = (f"The sensor model ({classified.sensors.model}) labelled the "
                          f"readings faulty" + (f": {shown}." if shown else "."))
                reasons.append(reason)
                alerts.append(Alert(point.id, "warning", reason,
                                    evidence_readings=tuple(r.index for r in usable)))
            if faulty_frames:
                model = next(v.label.model for v in images if v.label.value == "faulty")
                reason = (f"{len(faulty_frames)} of {len(images)} frames labelled "
                          f"faulty by {model}.")
                reasons.append(reason)
                alerts.append(Alert(point.id, "warning", reason, evidence_frames=faulty_frames))
            return PointResult(point.id, "anomaly", tuple(reasons), tuple(alerts))

        labels = [classified.sensors, *(v.label for v in images)]
        if all(label.value == "unknown" for label in labels):
            why = sorted({label.reason or "no reason given" for label in labels})
            return PointResult(point.id, "insufficient_data",
                               (f"No model gave a verdict: {'; '.join(why)}.",))
        return PointResult(point.id, "normal", ("Nothing at this point was labelled faulty.",))
