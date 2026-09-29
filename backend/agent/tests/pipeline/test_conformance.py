"""Every registered stage implementation, against the contract's rules.

The list of implementations is conformance.py; this file is the checks."""

from __future__ import annotations

import hashlib
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

from cropwatcher.pipeline.contracts import (
    CleanResult,
    FlightContext,
    InspectionPoint,
    PointData,
)
from cropwatcher.pipeline.sources import LocalFlightSource
from cropwatcher.pipeline.stages.enhance.stub import StubEnhancer
from tests.pipeline.conformance import CLASSIFIERS, CLEANERS, ENHANCERS

FIXTURE = Path(__file__).parent / "fixtures" / "data"
FORBIDDEN = ("cropwatcher.flight", "cropwatcher.session", "cropwatcher.api",
             "cropwatcher.sync", "cropwatcher.camera")


@pytest.fixture(scope="module")
def flight():
    source = LocalFlightSource(FIXTURE)
    return source.load("372bbdc4-d323-42bb-9e6c-29ef02e3794c")


@pytest.fixture
def ctx(tmp_path, flight) -> FlightContext:
    return FlightContext(flight_id=flight.flight_id, session_id=flight.session_id,
                         temp_unit=flight.temp_unit, ground_z_m=None,
                         started_at=flight.started_at, workdir=tmp_path / "work")


def points(flight):
    empty = PointData(InspectionPoint("EMPTY", None, 0, 0, 0.4), (), ())
    return [*flight.points, empty]


def hashes(data: PointData) -> dict[int, str]:
    return {f.seq: hashlib.sha256(f.path.read_bytes()).hexdigest() for f in data.frames}


def imports_of(cls) -> set[str]:
    module = inspect.getmodule(cls)
    assert module is not None
    code = (f"import sys, {module.__name__}; "
            f"print('\\n'.join(m for m in sys.modules if m.startswith('cropwatcher')))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         check=True)
    return set(out.stdout.split())


ALL = [*CLEANERS, *ENHANCERS, *CLASSIFIERS]


@pytest.mark.parametrize("stage", ALL, ids=lambda c: c.__name__)
def test_rule_1_self_contained(stage):
    loaded = imports_of(stage)
    assert not [m for m in loaded if m.startswith(FORBIDDEN)]


@pytest.mark.parametrize("stage", ALL, ids=lambda c: c.__name__)
def test_every_stage_names_and_versions_itself(stage):
    instance = stage()
    assert isinstance(instance.name, str) and instance.name
    assert isinstance(instance.version, str) and instance.version


@pytest.mark.parametrize("cleaner", CLEANERS, ids=lambda c: c.__name__)
class TestCleaners:
    def test_readings_come_back_unchanged_and_flags_point_at_real_rows(self, cleaner,
                                                                       flight, ctx):
        for data in points(flight):
            result = cleaner().clean(data, ctx)
            assert result.readings is data.readings or result.readings == data.readings
            indexes = {r.index for r in data.readings}
            columns = {c for r in data.readings for c in r.values}
            for flag in result.flags:
                assert flag.index in indexes
                assert flag.column is None or flag.column in columns
                assert flag.reason

    def test_the_same_input_gives_the_same_flags(self, cleaner, flight, ctx):
        data = flight.points[0]
        assert cleaner().clean(data, ctx).flags == cleaner().clean(data, ctx).flags


@pytest.mark.parametrize("enhancer", ENHANCERS, ids=lambda c: c.__name__)
class TestEnhancers:
    def test_one_frame_out_per_frame_in_in_order(self, enhancer, flight, ctx):
        for data in points(flight):
            result = enhancer().enhance(data, ctx)
            assert tuple(f.frame for f in result.frames) == data.frames

    def test_files_only_under_the_workdir_and_originals_untouched(self, enhancer, flight,
                                                                  ctx):
        for data in points(flight):
            before = hashes(data)
            result = enhancer().enhance(data, ctx)
            for f in result.frames:
                if f.path is None:
                    assert f.note, "a frame not enhanced must say why"
                else:
                    assert ctx.workdir in f.path.parents
                    assert f.scale in (1, 2, 4)
            assert hashes(data) == before

    def test_the_same_input_gives_the_same_output(self, enhancer, flight, ctx):
        data = flight.points[0]
        first = [(f.method, f.scale, f.path) for f in enhancer().enhance(data, ctx).frames]
        again = [(f.method, f.scale, f.path) for f in enhancer().enhance(data, ctx).frames]
        assert first == again


@pytest.mark.parametrize("classifier", CLASSIFIERS, ids=lambda c: c.__name__)
class TestClassifiers:
    def labels(self, classifier, data, ctx):
        clean = CleanResult(data.readings, ())
        enhanced = StubEnhancer().enhance(data, ctx)
        return classifier().classify(data, clean, enhanced, ctx)

    def test_every_frame_labelled_in_order(self, classifier, flight, ctx):
        for data in points(flight):
            result = self.labels(classifier, data, ctx)
            assert tuple(v.seq for v in result.images) == tuple(f.seq for f in data.frames)
            for label in [result.sensors, *(v.label for v in result.images)]:
                assert label.value in ("normal", "faulty", "unknown")
                assert label.value != "unknown" or label.reason
                assert "@" in label.model

    def test_the_same_input_gives_the_same_labels(self, classifier, flight, ctx):
        data = flight.points[0]
        assert self.labels(classifier, data, ctx) == self.labels(classifier, data, ctx)

    def test_feature_names_carry_units(self, classifier, flight, ctx):
        result = self.labels(classifier, flight.points[0], ctx)
        for name in result.features:
            assert "_" in name, f"feature {name!r} should name its unit"


def test_the_fixture_is_where_the_tests_think_it_is():
    assert (FIXTURE / "fixture.json").exists()
