"""Which implementation each stage uses — the composition root.

THIS IS THE LINE A STAGE OWNER CHANGES TO PLUG IN: replace a stub with your
class, add your class to tests/pipeline/conformance.py, and every contract
check runs against it (docs/handoffs/sprint-1/done/dpp-contract.txt, "How you plug in").
"""

from __future__ import annotations

from dataclasses import dataclass

from cropwatcher.pipeline.contracts import Classifier, Cleaner, Enhancer, Interpreter
from cropwatcher.pipeline.stages.classify.blocks import BlocksClassifier
from cropwatcher.pipeline.stages.classify.ground import GroundClassifier
from cropwatcher.pipeline.stages.clean.robust import RobustCleaner
from cropwatcher.pipeline.stages.enhance.clahe import ClaheEnhancer
from cropwatcher.pipeline.stages.interpret.findings import FindingInterpreter


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
        enhancer=ClaheEnhancer(),         # contrast, not resolution: ml/enhance-eval/RESULTS.txt
        classifier=BlocksClassifier(),    # blocks against expected: ml/anomaly-eval/
        interpreter=FindingInterpreter(), # events → findings and verdicts
    )


def session_stages() -> Stages:
    """A session around its flights: the same cleaner, enhancer and interpreter;
    the ground classifier in place of the flight's (stages/classify/ground.py)."""
    stages = default_stages()
    return Stages(cleaner=stages.cleaner, enhancer=stages.enhancer,
                  classifier=GroundClassifier(), interpreter=stages.interpreter)
