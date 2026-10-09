"""Runs the stages over one flight.

    clean → enhance → classify → interpret      once, over the whole flight
    then:                                       one FlightResult, saved by the sink

The whole flight goes through each stage once (contract v2): a block of
unusual readings can start in transit and end at a point, and only a stage
that sees the whole flight can find it. The inspection points are a view —
interpret gives each one its verdict, and the summary counts each one's
readings, flags and frames.

A STAGE THAT FAILS NEVER TAKES THE FLIGHT WITH IT. Its failure is recorded
(StageFailure: which stage, why — point "flight") and the flight carries on as
far as it honestly can:

    clean fails       nothing is analysed: every point insufficient_data.
                      Analysing readings nobody checked is what cleaning
                      exists to stop.
    enhance fails     the original frames are used — they always exist.
    classify fails    every label is "unknown", with the failure as the reason.
    interpret fails   every point insufficient_data, with the failure as the
                      reason.

A stage that BREAKS THE CONTRACT — a cleaner that edits a reading, an enhancer
that returns the wrong number of frames — is treated exactly like one that
failed. The conformance tests catch this before a pull request lands; the
runner makes sure a regression in the field still cannot write a verdict on
data that does not line up.

THIS RUNS IN THE CALLER'S PROCESS. The CLI is not flying anything. The live
runner (story 4.9) will run in a process of its own — never a thread beside the
50 Hz flight loop, which shares one interpreter lock.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from cropwatcher.pipeline import PIPELINE_VERSION
from cropwatcher.pipeline.compose import Stages
from cropwatcher.pipeline.contracts import (
    WHOLE_FLIGHT,
    ClassifyResult,
    CleanResult,
    EnhancedFrame,
    EnhanceResult,
    FlightContext,
    FlightResult,
    FrameRecord,
    ImageVerdict,
    InspectionPoint,
    InterpretResult,
    Label,
    PointData,
    PointResult,
    StageError,
    StageFailure,
)
from cropwatcher.pipeline.sinks import ResultSink
from cropwatcher.pipeline.sources import FlightSource, LocalSessionSource

log = logging.getLogger(__name__)


class ContractBroken(StageError):
    """A stage returned something the contract forbids."""


def _why(e: Exception) -> str:
    return str(e) if isinstance(e, StageError) else f"{type(e).__name__}: {e}"


def _views(data: PointData, plan: tuple[InspectionPoint, ...]) -> tuple[InspectionPoint, ...]:
    """The points a verdict is given for: the mission's, or the flight itself."""
    return plan or (data.point,)


def _every_point(plan: tuple[InspectionPoint, ...], data: PointData,
                 reason: str) -> InterpretResult:
    return InterpretResult(tuple(PointResult(p.id, "insufficient_data", (reason,))
                                 for p in _views(data, plan)))


def _summary(data: PointData, plan: tuple[InspectionPoint, ...],
             clean: CleanResult | None) -> dict[str, Any]:
    """Per point: how many readings, flags and frames — the evidence a verdict
    rests on. Transit readings are counted under "_transit"."""
    flagged = {f.index for f in clean.flags} if clean else set()

    def count(point_id: str | None) -> dict[str, int]:
        readings = [r for r in data.readings if point_id is None or r.point_id == point_id]
        out = {"readings": len(readings),
               "frames": sum(1 for f in data.frames
                             if point_id is None or f.point_id == point_id)}
        if clean is not None:
            out["flags"] = sum(1 for r in readings if r.index in flagged)
        return out

    if not plan:
        return {data.point.id: count(None)}
    summary: dict[str, Any] = {p.id: count(p.id) for p in plan}
    transit = sum(1 for r in data.readings if r.point_id is None)
    if transit:
        summary["_transit"] = {"readings": transit}
    return summary


def _frames(enhanced: EnhanceResult, classified: ClassifyResult,
            ctx: FlightContext) -> tuple[FrameRecord, ...]:
    labels = {v.seq: v.label for v in classified.images}
    records = []
    for e in enhanced.frames:
        relative = None
        if e.path is not None:
            relative = str(e.path.relative_to(ctx.workdir))
        label = labels.get(e.frame.seq) or Label("unknown", None, "none@0", "not classified")
        records.append(FrameRecord(e.frame.seq, e.frame.t_s, e.frame.point_id, relative,
                                   e.method, e.quality, label))
    return tuple(records)


def run_stages(data: PointData, ctx: FlightContext,
               stages: Stages) -> tuple[FlightResult, list[StageFailure]]:
    """Every stage once over `data` (the whole flight). Returns the result
    (not yet saved) and the failures it carries."""
    plan = ctx.points
    failures: list[StageFailure] = []

    def failed(stage: str, e: Exception) -> str:
        reason = _why(e)
        if not isinstance(e, StageError):
            log.exception("%s failed on flight %s", stage, ctx.flight_id)
        failures.append(StageFailure(WHOLE_FLIGHT, stage, reason))
        return reason

    def result(interpreted: InterpretResult, clean: CleanResult | None,
               enhanced: EnhanceResult | None = None,
               classified: ClassifyResult | None = None) -> FlightResult:
        return FlightResult(
            flight_id=ctx.flight_id, pipeline_version=PIPELINE_VERSION,
            stages=stages.names(), created_at=datetime.now(UTC).isoformat(),
            points=interpreted.points, failures=tuple(failures),
            summary=_summary(data, plan, clean), session_id=ctx.session_id,
            temp_unit=ctx.temp_unit, findings=interpreted.findings,
            flags=clean.flags if clean else (),
            tracks=classified.tracks if classified else (),
            segments=classified.segments if classified else (),
            frames=_frames(enhanced, classified, ctx) if enhanced and classified else (),
            scope=ctx.scope,
        )

    # ── clean ────────────────────────────────────────────────────────────
    try:
        clean = stages.cleaner.clean(data, ctx)
        if clean.readings != data.readings:
            raise ContractBroken("the cleaner changed or dropped readings; it may only flag")
    except Exception as e:
        reason = failed("clean", e)
        return result(_every_point(plan, data,
                                   f"Cleaning failed, so nothing was analysed: {reason}"),
                      None), failures

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
            tuple(ImageVerdict(f.seq, "original", unknown) for f in data.frames), unknown)

    # ── interpret ────────────────────────────────────────────────────────
    try:
        interpreted = stages.interpreter.interpret(data, clean, enhanced, classified, ctx)
        wanted = tuple(p.id for p in _views(data, plan))
        if tuple(p.point_id for p in interpreted.points) != wanted:
            raise ContractBroken("the interpreter did not give every inspection point one "
                                 "verdict, in order")
    except Exception as e:
        reason = failed("interpret", e)
        interpreted = _every_point(plan, data, f"Interpreting failed: {reason}")
    return result(interpreted, clean, enhanced, classified), failures


def run_flight(flight_id: str, *, source: FlightSource, sink: ResultSink,
               stages: Stages) -> tuple[FlightResult, str]:
    """Load, run every stage once over the flight, save. Returns the result and
    where it went."""
    flight = source.load(flight_id)
    ctx = FlightContext(
        flight_id=flight.flight_id, session_id=flight.session_id,
        temp_unit=flight.temp_unit, ground_z_m=flight.ground_z_m,
        started_at=flight.started_at, workdir=sink.workdir(flight.flight_id), mode="batch",
        points=flight.plan,
    )
    result, _ = run_stages(flight.whole, ctx, stages)
    return result, sink.save(result)


#: A session's samples come once a second (sync/samples.py, the 1 Hz writer).
SESSION_PERIOD_S = 1.0


def run_session(session_id: str, *, source: LocalSessionSource, sink: ResultSink,
                stages: Stages) -> tuple[FlightResult, str]:
    """The session around its flights — its one-a-second samples and the frames
    taken outside its flights — through every stage once. The result carries
    scope "session" and the session's id in flight_id."""
    session = source.load(session_id)
    ctx = FlightContext(
        flight_id=session.session_id, session_id=session.session_id, temp_unit="C",
        ground_z_m=None, started_at=session.started_at,
        workdir=sink.workdir(session.session_id), mode="batch", points=(),
        scope="session", period_s=SESSION_PERIOD_S,
    )
    result, _ = run_stages(session.whole, ctx, stages)
    return result, sink.save(result)
