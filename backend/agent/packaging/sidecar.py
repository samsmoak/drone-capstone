"""Frozen entry point for the desktop app's bundled agent.

The Tauri app ships this as a sidecar binary so a user never installs Python.
It is deliberately the *whole* CLI rather than a hardcoded `serve`, because the
diagnostic commands are what you reach for when a drone will not connect and
there is no terminal with a venv in it:

    cropwatcher-agent serve      # what the desktop app launches
    cropwatcher-agent check      # what you run when it will not fly

`freeze_support()` comes first and unconditionally. Without it, any library
that spawns a process re-executes this binary from the top instead of starting
a worker, and a frozen app forks itself until it is killed.
"""

from __future__ import annotations

import multiprocessing
import sys

from cropwatcher.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
