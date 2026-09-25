# CropWatcher desktop

The Tauri app that bundles the flight agent. How it works, how to build it, and
the rules that cost time to discover: [docs/features/desktop/desktop-app.txt](../docs/features/desktop/desktop-app.txt).

```bash
node scripts/setup.mjs     # once, from the repo root: checks and installs everything
cd desktop
pnpm app                   # freeze + verify the agent, build the app, open it
```

The same commands on macOS and Windows. `pnpm sidecar` freezes the agent
alone; `pnpm tauri build` makes the installer (.dmg or .exe).
