"""Runs the stages, one inspection point at a time.

    for each point:  clean → enhance → classify → interpret
    then:            one FlightResult, saved by the sink

A STAGE THAT FAILS NEVER TAKES THE FLIGHT WITH IT. Its failure is recorded
(StageFailure: which point, which stage, why) and the point carries on as far
as it honestly can:

    clean fails       the point stops here: insufficient_data. Analysing
                      readings nobody checked is what cleaning exists to stop.
    enhance fails     the original frames are used — they always exist.
    classify fails    every label is "unknown", with the failure as the reason.
    interpret fails   insufficient_data, with the failure as the reason.

A stage that BREAKS THE CONTRACT — a cleaner that edits a reading, an enhancer
that returns the wrong number of frames — is treated exactly like one that
failed. The conformance tests catch this before a pull request lands; the
runner makes sure a regression in the field still cannot write a verdict on
data that does not line up.

THIS RUNS IN THE CALLER'S PROCESS. The CLI is not flying anything. The live
runner (story 4.9) will call run_point in a process of its own — never a thread
beside the 50 Hz flight loop, which shares one interpreter lock.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cropwatcher.pipeline import PIPELINE_VERSION
from cropwatcher.pipeline.compose import Stages
from cropwatcher.pipeline.contracts import (
    ClassifyResult,
    EnhancedFrame,
    EnhanceResult,
    FlightContext,
    FlightResult,
    ImageVerdict,
    Label,
    PointData,
    PointResult,
    StageError,
    StageFailure,
)
from cropwatcher.pipeline.sinks import ResultSink
from cropwatcher.pipeline.sources import FlightSource

log = logging.getLogger(__name__)


class ContractBroken(StageError):
    """A stage returned something the contract forbids."""


@dataclass(frozen=True)
class PointOutcome:
    result: PointResult
    failures: tuple[StageFailure, ...]
    summary: dict[str, Any]


def _why(e: Exception) -> str:
    return str(e) if isinstance(e, StageError) else f"{type(e).__name__}: {e}"


def run_point(data: PointData, ctx: FlightContext, stages: Stages) -> PointOutcome:
    point = data.point.id
    failures: list[StageFailure] = []

    def failed(stage: str, e: Exception) -> str:
        reason = _why(e)
        if not isinstance(e, StageError):
            log.exception("%s failed at point %s", stage, point)
        failures.append(StageFailure(point, stage, reason))
        return reason

    summary: dict[str, Any] = {"readings": len(data.readings), "frames": len(data.frames)}

    # ── clean ────────────────────────────────────────────────────────────
    try:
        clean = stages.cleaner.clean(data, ctx)
        if clean.readings != data.readings:
            raise ContractBroken("the cleaner changed or dropped readings; it may only flag")
    except Exception as e:
        reason = failed("clean", e)
        return PointOutcome(PointResult(point, "insufficient_data",
                                        (f"Cleaning failed, so nothing was analysed: {reason}",)),
                            tuple(failures), summary)
    summary["flags"] = len(clean.flags)

    # ── enhance ──────────────────────────────────────────────────────────
    try:
        enhanced = stages.enhancer.enhance(data, ctx)
        if tuple(f.frame for f in enhanced.frames) != data.frames:
            raise ContractBroken("the enhancer did not return one frame per input frame, "
                                 "in order")
        for f in enhanced.frames:
            if f.path is not None and ctx.workdir not in f.path.parents:
                raise ContractBroken(f"the enhancer wrote {f.path} outside its workdir")
    except Exception as e:
        reason = failed("enhance", e)
        enhanced = EnhanceResult(tuple(
            EnhancedFrame(f, None, "identity", 1, f"enhancement failed: {reason}")
            for f in data.frames))

    # ── classify ─────────────────────────────────────────────────────────
    try:
        classified = stages.classifier.classify(data, clean, enhanced, ctx)
        if tuple(v.seq for v in classified.images) != tuple(f.seq for f in data.frames):
            raise ContractBroken("the classifier did not label every frame, in order")
    except Exception as e:
        reason = failed("classify", e)
        model = f"{stages.classifier.name}@{stages.classifier.version}"
        unknown = Label("unknown", None, model, f"classification failed: {reason}")
        classified = ClassifyResult(
            tuple(ImageVerdict(f.seq, "original", unknown) for f in data.frames), unknown, {})

    # ── interpret ────────────────────────────────────────────────────────
    try:
        result = stages.interpreter.interpret(data, clean, classified, ctx)
    except Exception as e:
        reason = failed("interpret", e)
        result = PointResult(point, "insufficient_data", (f"Interpreting failed: {reason}",))
    return PointOutcome(result, tuple(failures), summary)


def run_flight(flight_id: str, *, source: FlightSource, sink: ResultSink,
               stages: Stages) -> tuple[FlightResult, str]:
    """Load, run every point, save. Returns the result and where it went."""
    flight = source.load(flight_id)
    ctx = FlightContext(
        flight_id=flight.flight_id, session_id=flight.session_id,
        temp_unit=flight.temp_unit, ground_z_m=flight.ground_z_m,
        started_at=flight.started_at, workdir=sink.workdir(flight.flight_id), mode="batch",
    )
    outcomes = [run_point(point, ctx, stages) for point in flight.points]
    summary: dict[str, Any] = {o.result.point_id: o.summary for o in outcomes}
    if flight.unassigned_readings:
        summary["_transit"] = {"readings": flight.unassigned_readings}
    result = FlightResult(
        flight_id=flight.flight_id, pipeline_version=PIPELINE_VERSION,
        stages=stages.names(), created_at=datetime.now(UTC).isoformat(),
        points=tuple(o.result for o in outcomes),
        failures=tuple(f for o in outcomes for f in o.failures),
        summary=summary,
    )
    return result, sink.save(result)
