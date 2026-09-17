"""One live telemetry stream per connection.

Everything that needs to know what the drone is doing reads from here: the
in-flight safety guards, the CSV row builder, the desktop app's live windows
and the Supabase upload. One subscription, many readers.

It replaces a pattern that hurt the steady hover: ``Flight.position()`` built a
brand-new log subscription on every call — four times a second during a hover —
adding radio traffic at exactly the moment the link matters most.

Two facts about the Crazyflie log system shape this module:

- **A log block carries at most 26 bytes** (``cflib LogConfig.MAX_LEN``).
  Variables are packed into as many blocks as they need, by the size of the type
  the *drone* reports for each one.
- **Firmware builds publish different variables.** Anything not in the drone's
  own TOC is skipped and listed in :attr:`TelemetryStream.missing`, rather than
  failing the connection. The windows show "not available on this drone".
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from cflib.crazyflie.log import LogConfig

log = logging.getLogger(__name__)

PERIOD_MS = 100                     # 10 Hz
MAX_BLOCK_BYTES = 26                # cflib LogConfig.MAX_LEN

CTYPE_BYTES = {
    "uint8_t": 1, "int8_t": 1,
    "uint16_t": 2, "int16_t": 2, "FP16": 2,
    "uint32_t": 4, "int32_t": 4, "float": 4,
}

# What the live windows and guards read, grouped by the window that shows it.
# Order matters: the first variable is the stream's anchor (see `on_update`).
WINDOWS: dict[str, tuple[str, ...]] = {
    "flight": (
        "stateEstimate.x", "stateEstimate.y", "stateEstimate.z",
        "stateEstimate.vx", "stateEstimate.vy", "stateEstimate.vz",
        "stabilizer.roll", "stabilizer.pitch", "stabilizer.yaw",
        "stabilizer.thrust", "supervisor.info",
    ),
    "power": (
        "pm.vbat", "pm.state", "sys.canfly",
        "motor.m1", "motor.m2", "motor.m3", "motor.m4",
    ),
    "environment": ("baro.temp", "baro.pressure"),
    "motion": ("acc.x", "acc.y", "acc.z", "gyro.x", "gyro.y", "gyro.z"),
    "positioning": (
        "lighthouse.bsReceive", "lighthouse.bsActive",
        "lighthouse.bsCalVal", "lighthouse.bsGeoVal", "lighthouse.bsAvailable",
        "kalman.varPX", "kalman.varPY", "kalman.varPZ",
    ),
}

ALL_VARIABLES: tuple[str, ...] = tuple(v for names in WINDOWS.values() for v in names)
ANCHOR = ALL_VARIABLES[0]


@dataclass(frozen=True)
class Snapshot:
    """The latest value of every stream variable, and when it arrived."""

    values: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))
    updated_at: float | None = None       # monotonic seconds

    def get(self, name: str) -> float | None:
        return self.values.get(name)

    def age_s(self, now: float) -> float | None:
        return None if self.updated_at is None else now - self.updated_at


def pack_blocks(
    names: Iterable[str], toc: Mapping[str, Mapping[str, Any]]
) -> tuple[list[list[tuple[str, str]]], list[str]]:
    """Group variables into log blocks of at most 26 bytes.

    Returns ``(blocks, missing)``. First-fit in the given order, so related
    variables stay in the same block and arrive together.
    """
    blocks: list[list[tuple[str, str]]] = []
    sizes: list[int] = []
    missing: list[str] = []

    for complete in names:
        group, _, name = complete.partition(".")
        element = toc.get(group, {}).get(name)
        if element is None:
            missing.append(complete)
            continue
        size = CTYPE_BYTES.get(element.ctype)
        if size is None:
            log.warning("unknown log type %s for %s, skipping", element.ctype, complete)
            missing.append(complete)
            continue

        for i, used in enumerate(sizes):
            if used + size <= MAX_BLOCK_BYTES:
                blocks[i].append((complete, element.ctype))
                sizes[i] += size
                break
        else:
            blocks.append([(complete, element.ctype)])
            sizes.append(size)

    return blocks, missing


class TelemetryStream:
    """A persistent 10 Hz subscription to :data:`ALL_VARIABLES`."""

    def __init__(
        self,
        scf: Any,
        variables: Iterable[str] = ALL_VARIABLES,
        *,
        period_ms: int = PERIOD_MS,
        clock: Callable[[], float] = time.monotonic,
        log_config_factory: Callable[[str, int], Any] = LogConfig,
    ) -> None:
        self._scf = scf
        self._clock = clock
        self._period_ms = period_ms
        self._factory = log_config_factory

        variables = tuple(variables)
        self.blocks, self.missing = pack_blocks(variables, scf.cf.log.toc.toc)
        self.available = tuple(name for block in self.blocks for name, _ in block)
        self._anchor = self.available[0] if self.available else None

        self._lock = threading.Lock()
        self._values: dict[str, float] = {}
        self._updated_at: float | None = None
        self._configs: list[Any] = []
        self._subscribers: list[Callable[[Snapshot], None]] = []

    # ── lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._configs:
            return
        for i, block in enumerate(self.blocks):
            cfg = self._factory(f"cw{i}", self._period_ms)
            for name, ctype in block:
                cfg.add_variable(name, ctype)
            cfg.data_received_cb.add_callback(self._on_data)
            self._scf.cf.log.add_config(cfg)
            cfg.start()
            self._configs.append(cfg)
        if self.missing:
            log.info("telemetry: not published by this firmware: %s", ", ".join(self.missing))
        log.info("telemetry stream: %d variables in %d blocks at %d Hz",
                 len(self.available), len(self.blocks), 1000 // self._period_ms)

    def stop(self) -> None:
        for cfg in self._configs:
            try:
                cfg.stop()
            except Exception:
                log.debug("log block already stopped")
        self._configs.clear()

    # ── reading ──────────────────────────────────────────────────────────

    def snapshot(self) -> Snapshot:
        with self._lock:
            return Snapshot(MappingProxyType(dict(self._values)), self._updated_at)

    def subscribe(self, callback: Callable[[Snapshot], None]) -> Callable[[], None]:
        """Call `callback` once per anchor update (10 Hz). Returns an unsubscribe."""
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    # ── callback ─────────────────────────────────────────────────────────

    def _on_data(self, _timestamp: int, data: dict, _config: Any) -> None:
        # cflib's callback thread. Must never raise: an exception here stops
        # the stream silently and every guard reading it goes blind.
        try:
            now = self._clock()
            with self._lock:
                self._values.update({k: float(v) for k, v in data.items()})
                self._updated_at = now
                is_anchor = self._anchor in data
                subscribers = list(self._subscribers) if is_anchor else []
            if not subscribers:
                return
            snap = self.snapshot()
            for callback in subscribers:
                try:
                    callback(snap)
                except Exception:
                    log.exception("telemetry subscriber failed, continuing")
        except Exception:
            log.exception("telemetry block dropped")
