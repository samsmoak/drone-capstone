# Desktop app

**What it is.** A Tauri v2 window with three panels — status, manual control,
agent log — that bundles the flight agent as a sidecar binary, so an operator
installs one thing and never sees Python. Not a second copy of the web app.

**Where it lives.**

| | |
|---|---|
| `desktop/src-tauri/src/lib.rs` | Spawns and supervises the agent; `panic_stop` command |
| `desktop/src/main.ts`, `index.html` | The three panels; manual-control client |
| `backend/agent/packaging/` | PyInstaller spec, `build_sidecar.sh`, `verify_sidecar.py` |
| `.github/workflows/desktop-release.yml` | `.dmg` + `.exe` on a `v*` tag |
| `backend/supabase/migrations/…05_installers_bucket.sql` | Public `installers` bucket |
| `web/components/ui/download-buttons.tsx` | `/setup` buttons, live once a file exists |

Build locally: `backend/agent/packaging/build_sidecar.sh` then
`cd desktop && pnpm tauri build`. Rust lives in `~/.cargo/bin`, which a login
shell may not have on `PATH`.

## Decisions

- **The sidecar is spawned from Rust, never the webview.** The window holds no
  shell permission, so no script in it can start a process.
- **One-file PyInstaller binary** (27 MB; the `.dmg` is 30 MB). A folder of loose
  libraries beside the app is worse to ship and to sign.
- **The whole CLI is frozen, not just `serve`**, so `cropwatcher-agent check` is
  available on a machine with no Python when a drone will not connect.
- **Installers go to a public bucket at stable paths** (`latest/CropWatcher-macos.dmg`),
  overwritten by CI. The download buttons never need a redeploy; they HEAD the
  object and show "coming soon" until it exists.
- **Cut motors is `P`, not `Space`** — the operator's call: Space is too easy to
  hit by accident, and cutting motors in the air drops the drone. The on-screen
  button stays for the reachable case.

## Invariants

- **Pass `--exit-with-parent`, and never rely on killing the child.** A one-file
  PyInstaller binary is two processes. Measured from the built app:
  `desktop(43661) → bootloader(43666) → python(43670)`, and the last one holds
  the port and the radio. Tauri kills only the bootloader; the Python process
  was re-parented to `launchd` and kept the radio, so the next launch reported
  "no drone found". The agent now exits when stdin closes — verified on quit and
  on `kill -9` of the app.
- **Verify the frozen binary, not the build.** A binary missing libusb builds,
  launches and serves `/health`; it fails only when a radio is plugged in.
  `verify_sidecar.py` asserts cflib *enumerated USB* ("Looking for devices") and
  that no bundling error appeared — "no drone found" is the correct answer with
  no dongle, a missing backend is not. Exit codes cannot tell these apart.
- **uvicorn's protocol modules are hidden imports.** It selects them by string
  name; without them the binary starts and cannot upgrade a WebSocket.
- **A probe WebSocket key must be exactly 16 bytes.** A 17-byte key gets a 400
  indistinguishable from "websockets not bundled".
- **Space must be blocked on keyup too.** WebKit activates a focused button on
  Space *keyup*; blocking keydown alone leaves a focused Cut motors button one
  Space away. Verified with real key events: 0 stops from Space, focused or not.
- **Neither half cross-compiles.** macOS builds the `.dmg`, Windows the `.exe`,
  each on its own runner. `macos-latest` is Apple silicon: no Intel build.

## Not yet verified

The CI workflow has never run. No Windows build exists. Nothing has talked to a
real Crazyradio from inside the bundle — only that libusb loads and enumerates.
The `installers` migration is applied locally, not on the hosted project.
