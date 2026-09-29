"""Interpret: the classifier's labels → a verdict per inspection point.

THIS HOLDS NO TEMPERATURE OR PRESSURE THRESHOLD, and that is deliberate. A
"normal operating" limit is measured on the equipment (story 4.6: "define
normal thresholds"), never guessed — CLAUDE.md, flight invariant 1, and the
3.70 V threshold that refused good flights. Until the limits are measured, the
verdict rests on the classifier alone:

    no usable readings and no frames      insufficient_data
    every label "unknown"                 insufficient_data — and why
    any label "faulty"                    anomaly, with an alert quoting the
                                          evidence (reading indexes, frames)
    otherwise                             normal

Measured thresholds join here later, as a second source of alerts beside the
labels, each alert naming the reading and the limit it crossed.
"""

from __future__ import annotations

from cropwatcher.pipeline.contracts import (
    Alert,
    ClassifyResult,
    CleanResult,
    FlightContext,
    PointData,
    PointResult,
)


class LabelInterpreter:
    name = "labels"
    version = "1"

    def interpret(self, data: PointData, clean: CleanResult, classified: ClassifyResult,
                  ctx: FlightContext) -> PointResult:
        point = data.point.id
        usable = [r for r in clean.readings
                  if any(clean.usable(r.index, c) for c in r.values)]
        if not usable and not data.frames:
            return PointResult(point, "insufficient_data",
                               ("No usable readings and no frames at this point.",))

        faulty_frames = tuple(v.seq for v in classified.images if v.label.value == "faulty")
        sensors_faulty = classified.sensors.value == "faulty"
        if faulty_frames or sensors_faulty:
            reasons: list[str] = []
            alerts: list[Alert] = []
            if sensors_faulty:
                shown = ", ".join(f"{k} {v:.2f}" for k, v in classified.features.items())
                reason = (f"The sensor model ({classified.sensors.model}) labelled the "
                          f"readings faulty" + (f": {shown}." if shown else "."))
                reasons.append(reason)
                alerts.append(Alert(point, "warning", reason,
                                    evidence_readings=tuple(r.index for r in usable)))
            if faulty_frames:
                model = next(v.label.model for v in classified.images
                             if v.label.value == "faulty")
                reason = (f"{len(faulty_frames)} of {len(classified.images)} frames labelled "
                          f"faulty by {model}.")
                reasons.append(reason)
                alerts.append(Alert(point, "warning", reason, evidence_frames=faulty_frames))
            return PointResult(point, "anomaly", tuple(reasons), tuple(alerts))

        labels = [classified.sensors, *(v.label for v in classified.images)]
        if all(label.value == "unknown" for label in labels):
            why = sorted({label.reason or "no reason given" for label in labels})
            return PointResult(point, "insufficient_data",
                               (f"No model gave a verdict: {'; '.join(why)}.",))
        return PointResult(point, "normal", ("Nothing at this point was labelled faulty.",))
