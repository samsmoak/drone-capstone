"""hampel@1, loaded from the commit that last held it — for the comparison in
MEASUREMENTS.txt only. robust@1 replaced it on 2026-10-09; keeping a copy of
the file here would be a second implementation to drift, so its source is read
from git instead (`evaluate.py --cleaner hampel`).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

#: origin/main when hampel@1 was the agent's cleaner (PR #97).
COMMIT = "a68af86"
PATH = "backend/agent/cropwatcher/pipeline/stages/clean/hampel.py"

_source = subprocess.run(
    ["git", "show", f"{COMMIT}:{PATH}"], capture_output=True, text=True, check=True,
    cwd=Path(__file__).parent,
).stdout
exec(compile(_source, f"{COMMIT}:{PATH}", "exec"), globals())   # defines HampelCleaner
