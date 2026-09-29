"""The contract checks EVERY stage implementation must pass.

To plug a stage in, add your class to the list for its stage below. Every check
in tests/pipeline/test_conformance.py then runs against it on the fixture — a
real flight's readings and a set of frames — plus an empty point.

These are the rules marked [checked] in docs/handoffs/sprint-1/done/dpp-contract.txt:
  1  self-contained (no flight, session, api, sync or camera imports)
  2  one output per input, in order
  3  the input is never changed
  4  files only under ctx.workdir
  5  the same input gives the same output
  6  an empty point is a result, not an exception
"""

from __future__ import annotations

from cropwatcher.pipeline.stages.classify.stub import StubClassifier
from cropwatcher.pipeline.stages.clean.stub import StubCleaner
from cropwatcher.pipeline.stages.enhance.stub import StubEnhancer

#: Add your cleaner here (Kevin).
CLEANERS = [StubCleaner]
#: Add your enhancer here (Kevin).
ENHANCERS = [StubEnhancer]
#: Add your classifier here (Reagan).
CLASSIFIERS = [StubClassifier]
