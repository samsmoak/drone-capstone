# CropWatcher desktop

The Tauri app that bundles the flight agent. How it works, how to build it, and
the rules that cost time to discover: [docs/features/desktop/desktop-app.txt](../docs/features/desktop/desktop-app.txt).

```bash
node scripts/install.mjs   # from the repo root: check, build, install into Applications / for this user
```

For development, from the repo root: `node scripts/setup.mjs --dev` once, then
in `desktop/`: `pnpm app` (freeze + verify the agent, build, open it without
installing) or `pnpm tauri dev`. `pnpm sidecar` freezes the agent alone. The
same commands on macOS and Windows.
