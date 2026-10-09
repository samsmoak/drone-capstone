"""Which implementation each stage uses — the composition root.

THIS IS THE LINE A STAGE OWNER CHANGES TO PLUG IN: replace a stub with your
class, add your class to tests/pipeline/conformance.py, and every contract
check runs against it (docs/handoffs/sprint-1/done/dpp-contract.txt, "How you plug in").
"""

from __future__ import annotations

from dataclasses import dataclass

from cropwatcher.pipeline.contracts import Classifier, Cleaner, Enhancer, Interpreter
from cropwatcher.pipeline.stages.classify.stub import StubClassifier
from cropwatcher.pipeline.stages.clean.robust import RobustCleaner
from cropwatcher.pipeline.stages.enhance.stub import StubEnhancer
from cropwatcher.pipeline.stages.interpret.labels import LabelInterpreter


@dataclass(frozen=True)
class Stages:
    cleaner: Cleaner
    enhancer: Enhancer
    classifier: Classifier
    interpreter: Interpreter

    def names(self) -> dict[str, str]:
        return {
            "clean": f"{self.cleaner.name}@{self.cleaner.version}",
            "enhance": f"{self.enhancer.name}@{self.enhancer.version}",
            "classify": f"{self.classifier.name}@{self.classifier.version}",
            "interpret": f"{self.interpreter.name}@{self.interpreter.version}",
        }


def default_stages() -> Stages:
    return Stages(
        cleaner=RobustCleaner(),          # replaced hampel@1 (Kevin) on 2026-10-09
        enhancer=StubEnhancer(),          # Kevin: docs/handoffs/sprint-1/undone/dpp-enhance.txt
        classifier=StubClassifier(),      # Reagan: docs/handoffs/sprint-1/undone/dpp-classify.txt
        interpreter=LabelInterpreter(),   # Samuel
    )
