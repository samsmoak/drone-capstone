FEATURE-KIT — everything /feature and /copy-adapt depend on, for any project
================================================================================
The two skills (~/.claude/commands/feature.md, copy-adapt.md) run
`kit.py doctor` first, and `kit.py init` when anything is missing. So a brand-new
project gets the full setup on its first /feature run; an existing one only has
its gaps filled — the kit never overwrites a file.

This folder is deliberately OUTSIDE ~/.claude/commands/: any subfolder there is
picked up as a live skill namespace.

WHAT A PROJECT GETS (in its docs "hub" repo)
  docs/PROJECT_PROFILE.txt     repos, roles, bridge, call chain, gates, identity,
                               deploy, conventions — detected parts marked
                               CONFIRM, the rest ASK; doctor counts what is left
  docs/README.md               the router — one line per doc — and the feature
                               registry ("new, or an addition?")
  docs/features|design|platform/   where each kind of doc lives
  docs/_templates/feature.txt  the doc format: STATUS per surface, dated, first
  docs/graph.config.json       the project's facts the checker needs (repos, source
                               folders, extensions, endpoint + import patterns)
  docs/graph_check.py          the generic checker, vendored (versioned by
                               KIT_VERSION; `kit.py upgrade` refreshes it)
  docs/GRAPH_STATE.txt         BLOCK / WARN / DEBT / WATCH / OVERRIDES / RESOLVED
  docs/design/PREFERENCES.txt  asked-twice log; standing rules and where they live
  docs/design/components.txt   the shared layer + EXTRACTION CANDIDATES
  <repo>/<AREA>_PARITY.txt     per cross-repo port, on demand (parity-ledger)

COMMANDS (run from anywhere inside any repo of the project)
  kit.py doctor                what exists, what is missing, what is outdated
  kit.py init [--dry-run]      create what is missing
  kit.py upgrade               replace the vendored checker if the kit's is newer
  kit.py check                 run the project's graph check
  kit.py parity-ledger <target-repo> "<title>" --source <repo>

HOW IT DECIDES
  • The hub: this repo if it has docs/graph.config.json, else a sibling whose
    config lists this repo, else this repo.
  • The repos: an existing config's list always wins. Otherwise this repo plus
    the siblings its own CLAUDE.md / AGENTS.md / README.md NAME ("../x" or a
    standalone word — never a fragment like com.x.app). Every other sibling is
    listed as NOT included, for the user to confirm.
  • Stacks, gates, source folders, file types and endpoint holders are read from
    manifests and code (pubspec.yaml, go.mod, package.json, pyproject.toml,
    requirements.txt, Cargo.toml; a `class …Endpoints` / `export const
    …Endpoints` found in the code).

TESTS
  python3 -m unittest discover -s ~/.claude/feature-kit/tests -v
  (builds a throwaway multi-repo project, runs the kit on it, and checks that
  every file is generated, nothing is overwritten, an unrelated sibling is left
  out, and the generated checker catches ONE-WAY, STALE and PARITY faults)

CHANGING THE ENGINE
  Edit graph_check.py here, bump KIT_VERSION, run the tests, then
  `kit.py upgrade` in each project and compare its findings with the last run.
  Project-specific facts go in that project's graph.config.json — never here.

NOT BACKED UP. ~/.claude is not a git repo; this kit and the two skills exist on
this machine only. Keep a copy (a private repo) if they matter.
