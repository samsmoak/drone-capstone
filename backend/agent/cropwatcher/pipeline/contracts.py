"""The contract every pipeline stage builds against.

The same types as docs/handoffs/dpp-contract.txt — this file is now the
authority. Change a type here and every stage owner's code is affected, so a
change is agreed first and the contract doc updated in the same commit.

The unit of work is ONE INSPECTION POINT (PointData). A flight flown without a
mission is one point with id "flight". The same stage code runs after a flight
(batch) and, later, as each point completes (live).

UNITS: metres, seconds, hPa. Temperatures are in `FlightContext.temp_unit` —
whatever the operator chose at launch — and a stage converts them itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

#: A flight flown without a mission is one inspection point with this id.
WHOLE_FLIGHT = "flight"


class StageError(RuntimeError):
    """A stage cannot run at all (e.g. its model file is missing). The runner
    records the reason and carries on without that stage's output."""


# ── shared input ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FlightContext:
    flight_id: str
    session_id: str | None
    temp_unit: Literal["C", "F"]            # the unit of EVERY temperature value
    ground_z_m: float | None                # the floor's Lighthouse z at takeoff
    started_at: datetime                    # UTC
    workdir: Path                           # the ONLY place a stage may write files
    mode: Literal["batch", "live"] = "batch"


@dataclass(frozen=True)
class InspectionPoint:
    id: str                                 # stable id from the mission; "flight" if none
    label: str | None
    x_m: float                              # Lighthouse metres (absolute)
    y_m: float
    z_m: float                              # metres above the floor captured at takeoff


@dataclass(frozen=True)
class Reading:
    """One row of the flight CSV. `values` holds its numeric columns by the
    field names of TelemetryRow (telemetry/row.py); None = not recorded."""

    index: int
    recorded_at: datetime
    t_s: float                              # seconds since the flight's first row
    values: Mapping[str, float | None]


@dataclass(frozen=True)
class Frame:
    """One row of frames.csv."""

    seq: int
    recorded_at: datetime
    t_s: float                              # seconds since the flight's first row
    path: Path                              # the original image — READ ONLY
    width: int                              # 324 on the AI deck
    height: int                             # 244 on the AI deck
    x_m: float | None
    y_m: float | None
    z_m: float | None


@dataclass(frozen=True)
class PointData:
    point: InspectionPoint
    readings: tuple[Reading, ...]           # ordered by index
    frames: tuple[Frame, ...]               # ordered by seq; may be EMPTY


# ── stage 1: clean (story 4.2) ───────────────────────────────────────────

FlagKind = Literal["missing", "out_of_range", "spike", "stuck", "gap"]


@dataclass(frozen=True)
class ReadingFlag:
    index: int                              # Reading.index
    column: str | None                      # None = the whole row (e.g. a gap)
    kind: FlagKind
    reason: str                             # one sentence an inspector can read


@dataclass(frozen=True)
class CleanResult:
    readings: tuple[Reading, ...]           # EXACTLY the input readings, unchanged
    flags: tuple[ReadingFlag, ...]
    _bad: frozenset[tuple[int, str | None]] = field(default=frozenset(), repr=False,
                                                     compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_bad", frozenset((f.index, f.column) for f in self.flags))

    def usable(self, index: int, column: str) -> bool:
        """False when that value, or its whole row, was flagged."""
        return (index, column) not in self._bad and (index, None) not in self._bad


class Cleaner(Protocol):
    name: str
    version: str

    def clean(self, data: PointData, ctx: FlightContext) -> CleanResult: ...


# ── stage 2: enhance (story 4.3) ─────────────────────────────────────────


@dataclass(frozen=True)
class EnhancedFrame:
    frame: Frame
    path: Path | None                       # enhanced image under ctx.workdir;
                                            # None = not enhanced, use frame.path
    method: str                             # "identity", "clahe", "fsrcnn-x2", ...
    scale: int                              # 1, 2 or 4
    note: str | None = None                 # why it was skipped, when path is None


@dataclass(frozen=True)
class EnhanceResult:
    frames: tuple[EnhancedFrame, ...]       # ONE PER INPUT FRAME, SAME ORDER


class Enhancer(Protocol):
    name: str
    version: str

    def enhance(self, data: PointData, ctx: FlightContext) -> EnhanceResult: ...


# ── stage 3: classify (stories 4.4 and 4.6) ──────────────────────────────

LabelValue = Literal["normal", "faulty", "unknown"]


@dataclass(frozen=True)
class Label:
    value: LabelValue
    p_faulty: float | None                  # 0..1 from the model; None when unknown
    model: str                              # "<name>@<version>", from MODELS.json
    reason: str | None = None               # REQUIRED when value is "unknown"

    def __post_init__(self) -> None:
        if self.value == "unknown" and not self.reason:
            raise ValueError("an 'unknown' label must say why")
        if self.p_faulty is not None and not 0.0 <= self.p_faulty <= 1.0:
            raise ValueError("p_faulty must be between 0 and 1")


@dataclass(frozen=True)
class ImageVerdict:
    seq: int                                # Frame.seq
    source: Literal["original", "enhanced"]
    label: Label


@dataclass(frozen=True)
class ClassifyResult:
    images: tuple[ImageVerdict, ...]        # one per frame, same order
    sensors: Label                          # one label for the point's readings
    features: Mapping[str, float] = field(default_factory=dict)  # names carry units


class Classifier(Protocol):
    name: str
    version: str

    def classify(self, data: PointData, clean: CleanResult, enhanced: EnhanceResult,
                 ctx: FlightContext) -> ClassifyResult: ...


# ── stage 4: interpret (Samuel) ──────────────────────────────────────────

Verdict = Literal["normal", "anomaly", "insufficient_data"]
Severity = Literal["info", "warning", "critical"]


@dataclass(frozen=True)
class Alert:
    point_id: str
    severity: Severity
    reason: str
    evidence_readings: tuple[int, ...] = ()
    evidence_frames: tuple[int, ...] = ()


@dataclass(frozen=True)
class PointResult:
    point_id: str
    verdict: Verdict
    reasons: tuple[str, ...]
    alerts: tuple[Alert, ...] = ()


class Interpreter(Protocol):
    name: str
    version: str

    def interpret(self, data: PointData, clean: CleanResult, classified: ClassifyResult,
                  ctx: FlightContext) -> PointResult: ...


# ── the flight's result ──────────────────────────────────────────────────


@dataclass(frozen=True)
class StageFailure:
    point_id: str
    stage: str
    reason: str


@dataclass(frozen=True)
class FlightResult:
    flight_id: str
    pipeline_version: str
    stages: Mapping[str, str]                # stage → "name@version"
    created_at: str
    points: tuple[PointResult, ...]
    failures: tuple[StageFailure, ...] = ()
    #: Per point: how many readings, flags and frames it had — so a verdict can
    #: be judged against how much evidence it rested on.
    summary: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
