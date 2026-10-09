# This file was generated on 10/9/2026 with the assistance of the Cline extension in VS Code
# (ChatGPT, OpenAI, 2024). It provides an explicit package marker for the ``backend`` namespace,
# ensuring reliable imports in the test environment and when the repository root contains
# spaces or other path quirks.

"""Top‑level package marker for the ``backend`` namespace.

The test suite imports modules using the fully‑qualified name ``backend.agent...``.
In a pure‑namespace package layout (no ``__init__.py``), Python can resolve the
namespace only when the directory containing ``backend`` is on ``sys.path``.
In the execution sandbox the repository root is present, but the implicit
namespace handling sometimes fails due to the space in the path or the way the
test runner constructs its import path. Adding an empty ``__init__.py`` makes the
directory an explicit package and guarantees the imports succeed.
"""
