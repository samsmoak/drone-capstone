# CropWatcher desktop

The Tauri app that bundles the flight agent. How it works, how to build it, and
the rules that cost time to discover: [docs/features/desktop-app.md](../docs/features/desktop-app.md).

```bash
../backend/agent/packaging/build_sidecar.sh   # freeze + verify the agent
pnpm tauri build                              # .app + .dmg
```
