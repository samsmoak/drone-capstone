#!/usr/bin/env python3
"""feature-kit — everything /feature and /copy-adapt depend on, generated into
any project that does not have it yet.

    python3 ~/.claude/feature-kit/kit.py doctor          what exists, what is missing
    python3 ~/.claude/feature-kit/kit.py init [--dry-run] generate what is missing
    python3 ~/.claude/feature-kit/kit.py upgrade         refresh the project's checker
    python3 ~/.claude/feature-kit/kit.py check           run the project's graph check
    python3 ~/.claude/feature-kit/kit.py parity-ledger <target-repo> "<title>" --source <repo>

Run from anywhere inside a project repo. The kit NEVER overwrites a file that
exists — `init` only fills gaps, and `upgrade` replaces only the vendored
graph_check.py (never its config, which is the project's own).

WHERE THINGS GO. A project's docs live in one "hub" repo (docs/). From any repo
of the project the kit finds the hub: this repo if it has docs/graph.config.json,
else a sibling whose config lists this repo, else this repo becomes the hub.

THE DEPENDENCIES (what doctor checks, what init creates):
  profile       docs/PROJECT_PROFILE.txt   repos, roles, bridge, call chain,
                                           gates, identity, deploy, conventions
  router        docs/README.md             one line per doc — also the feature
                                           registry ("new, or an addition?")
  doc homes     docs/features|design|platform/
  template      docs/_templates/feature.txt  the doc format (STATUS first)
  config        docs/graph.config.json     what the checker needs to read code
  checker       docs/graph_check.py        vendored copy of the kit's engine
  state         docs/GRAPH_STATE.txt       BLOCK/WARN/DEBT/WATCH/OVERRIDES
  preferences   docs/design/PREFERENCES.txt  asked-twice log, standing rules
  components    docs/design/components.txt   shared layer + extraction flags
  parity ledger <target repo>/PARITY_*.txt   per cross-repo port (on demand)
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
TEMPLATES = KIT / "templates"
ENGINE = KIT / "graph_check.py"
TODAY = datetime.date.today().isoformat()
INSTRUCTION_FILES = ("CLAUDE.md", "AGENTS.md", "README.md")
MANIFESTS = ("pubspec.yaml", "go.mod", "package.json", "pyproject.toml", "requirements.txt", "Cargo.toml")
# A placeholder as the generator writes it — not the header that explains them.
PLACEHOLDER = re.compile(r"\b(?:ASK|UNKNOWN) —|\bCONFIRM:|\(CONFIRM\)")


# ── discovery ──────────────────────────────────────────────────────────────
def git(path, *args):
    try:
        return subprocess.run(["git", "-C", str(path), *args], capture_output=True,
                              text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


def repo_root(start):
    top = git(start, "rev-parse", "--show-toplevel")
    return Path(top) if top else None


def is_repo(p):
    return (p / ".git").exists() and any((p / m).exists() for m in MANIFESTS)


def engine_version(path):
    try:
        m = re.search(r"^KIT_VERSION\s*=\s*(\d+)", Path(path).read_text(), re.M)
        return int(m.group(1)) if m else 0
    except Exception:
        return None


def find_hub(root):
    """The repo whose docs/ serves this project."""
    if (root / "docs" / "graph.config.json").exists():
        return root
    for sib in sorted(root.parent.iterdir()):
        cfg = sib / "docs" / "graph.config.json"
        if sib == root or not cfg.exists():
            continue
        try:
            repos = json.loads(cfg.read_text()).get("repos", [])
        except Exception:
            continue
        for r in repos:
            if (sib / "docs" / r["path"]).resolve() == root.resolve():
                return sib
    return root


def instruction_text(repo):
    out = ""
    for f in INSTRUCTION_FILES:
        p = repo / f
        if p.exists():
            try:
                out += p.read_text(errors="ignore") + "\n"
            except Exception:
                pass
    return out


def detect_repos(root):
    """This repo plus the siblings its own instructions name. Other sibling repos
    are returned separately — to be CONFIRMED, never silently included: a folder
    of unrelated projects is common, and a wrong repo pollutes every check."""
    text = instruction_text(root)
    included, others = [root], []
    for sib in sorted(root.parent.iterdir()):
        if sib == root or not sib.is_dir() or not is_repo(sib):
            continue
        # A path ("../name", "name/") or a standalone word — not a fragment of a
        # dotted identifier: "com.acme.app" must not pull in a sibling "acme".
        n = re.escape(sib.name)
        named = re.search(rf"\.\./{n}(?![\w-])|(?<![\w.-]){n}(?![\w.-])", text)
        (included if named else others).append(sib)
    return included, others


def detect_stack(repo):
    """What a repo is, how it is gated, and how its code reaches the server."""
    info = {"name": repo.name, "stack": [], "role": "", "gates": [], "source_dirs": [],
            "extensions": [], "endpoint_refs": {}, "imports": {}, "import_roots": {},
            "call_chain": ""}
    ls = lambda *names: [d for d in names if (repo / d).is_dir()]

    if (repo / "pubspec.yaml").exists():
        pub = (repo / "pubspec.yaml").read_text(errors="ignore")
        info["stack"].append("Flutter/Dart")
        info["role"] = "client (Flutter)"
        if "build_runner" in pub:
            info["gates"].append("dart run build_runner build --delete-conflicting-outputs  (after codegen edits)")
        info["gates"] += ["flutter analyze", "flutter test"]
        info["source_dirs"] += ls("lib", "test")
        info["extensions"].append("dart")
        info["imports"][".dart"] = r"^import\s+'([^']+)'"
        info["import_roots"]["package:"] = "lib"
        cls = _grep_first(repo / "lib", "*.dart", r"^\s*(?:abstract\s+)?class\s+(\w*Endpoints?)\b")
        if cls:
            info["endpoint_refs"][".dart"] = rf"\b{cls[0]}\.(\w+)"
            info["call_chain"] = f"CONFIRM: screen -> repository -> {cls[0]}.<name>  ({cls[1]})"

    if (repo / "go.mod").exists():
        info["stack"].append("Go")
        info["role"] = info["role"] or "backend (Go)"
        info["gates"] += ["go build ./...", "go vet ./...", "go test ./..."]
        info["source_dirs"] += ls("internal", "cmd", "pkg", "api")
        info["extensions"].append("go")

    if (repo / "package.json").exists():
        try:
            pkg = json.loads((repo / "package.json").read_text())
        except Exception:
            pkg = {}
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        web = next((f for f in ("next", "react", "vue", "svelte", "@angular/core") if f in deps), None)
        info["stack"].append(f"Node ({web})" if web else "Node")
        info["role"] = info["role"] or (f"web ({web})" if web else "node")
        pm = "pnpm" if (repo / "pnpm-lock.yaml").exists() else "yarn" if (repo / "yarn.lock").exists() else "npm run"
        scripts = pkg.get("scripts", {})
        info["gates"] += [f"{pm} {s}" for s in ("typecheck", "lint", "test", "build") if s in scripts]
        info["source_dirs"] += ls("src", "app", "lib", "pages", "components")
        ts = (repo / "tsconfig.json").exists()
        info["extensions"] += ["ts", "tsx"] if ts else ["js", "jsx"]
        imp = r"from\s+'(@/[^']+|\.{1,2}/[^']+)'"
        for e in (("ts", "tsx") if ts else ("js", "jsx")):
            info["imports"]["." + e] = imp
        if (repo / "src").is_dir():
            info["import_roots"]["@/"] = "src"
        base = repo / "src" if (repo / "src").is_dir() else repo
        cls = _grep_first(base, "*.ts", r"^\s*export\s+const\s+(\w*Endpoints?)\b")
        if cls:
            for e in ("ts", "tsx"):
                info["endpoint_refs"]["." + e] = rf"\b{cls[0]}\.(\w+)"
            info["call_chain"] = (info["call_chain"] + "; " if info["call_chain"] else "") + \
                f"CONFIRM: component -> api module -> {cls[0]}.<name>  ({cls[1]})"

    if (repo / "pyproject.toml").exists() or (repo / "requirements.txt").exists():
        info["stack"].append("Python")
        info["role"] = info["role"] or "python"
        py = (repo / "pyproject.toml").read_text(errors="ignore") if (repo / "pyproject.toml").exists() else ""
        info["gates"] += (["ruff check ."] if "ruff" in py else []) + (["mypy ."] if "mypy" in py else []) + ["pytest"]
        info["source_dirs"] += ls("src", "app", "tests")
        info["extensions"].append("py")

    if (repo / "Cargo.toml").exists():
        info["stack"].append("Rust")
        info["role"] = info["role"] or "rust"
        info["gates"] += ["cargo check", "cargo clippy", "cargo test"]
        info["source_dirs"] += ls("src", "tests")
        info["extensions"].append("rs")

    info["role"] = info["role"] or "UNKNOWN"
    info["mainline"] = _mainline(repo)
    info["email"] = git(repo, "config", "user.email") or "UNKNOWN"
    info["committers"] = len({a for a in git(repo, "log", "-200", "--format=%ae").split() if a})
    return info


def _grep_first(base, pattern, rx):
    """(captured name, relative path) of the first file whose text matches rx."""
    if not base.is_dir():
        return None
    r = re.compile(rx, re.M)
    for f in sorted(base.rglob(pattern)):
        if "node_modules" in f.parts or ".g." in f.name or ".freezed." in f.name:
            continue
        try:
            m = r.search(f.read_text(errors="ignore"))
        except Exception:
            continue
        if m:
            return m.group(1), str(f.relative_to(base.parent if base.name in ("lib", "src") else base))
    return None


def _mainline(repo):
    head = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if head:
        return head.split("/", 1)[-1]
    branches = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/").split()
    return "main" if "main" in branches else "master" if "master" in branches else (branches[0] if branches else "main")


# ── generation ─────────────────────────────────────────────────────────────
def build_config(hub, repos):
    docs = hub / "docs"
    infos = [detect_stack(r) for r in repos]
    exts, src, refs, imps, roots = [], [], {}, {}, {}
    for i in infos:
        exts += [e for e in i["extensions"] if e not in exts]
        src += [d for d in i["source_dirs"] if d not in src]
        for k, v in i["endpoint_refs"].items():
            if k in refs and refs[k] != v:
                # Two repos, two endpoint holders for one file type: match either.
                a = re.search(r"\\b(.+)\\\.\(", refs[k]).group(1)
                b = re.search(r"\\b(.+)\\\.\(", v).group(1)
                refs[k] = rf"\b(?:{a}|{b})\.(\w+)"
            else:
                refs[k] = v
        imps.update(i["imports"])
        roots.update(i["import_roots"])
    mainlines = {i["mainline"] for i in infos}
    cfg = {
        "kit_version": engine_version(ENGINE),
        "project": hub.name,
        "doc_roots": ["features", "platform", "design"],
        "doc_glob": "**/*.txt",
        "index_names": ["README.txt"],
        "features_root": "features",
        "design_root": "design",
        "state_file": "GRAPH_STATE.txt",
        "mainline": mainlines.pop() if len(mainlines) == 1 else "main",
        "repos": [{"name": r.name, "path": os.path.relpath(r, docs)} for r in repos],
        "source_dirs": src or ["src", "lib"],
        "prefix_dirs": [d for d in ("lib", "internal", "src", "pkg") if d in src],
        "marker_dirs": [d for d in src if d not in ("test", "tests")],
        # No recognised manifest anywhere: fall back to the common source types
        # rather than an empty list, which would make every path pattern match
        # nothing (a silent all-clear).
        "extensions": exts or ["py", "ts", "tsx", "js", "jsx", "go", "rb", "java", "kt", "swift", "dart", "rs"],
        "generated_markers": [".g.", ".freezed.", ".generated.", ".pb."],
        "endpoint_refs": refs,
        "imports": imps,
        "import_roots": roots,
        "module_hop": r"(repository|_api|/api|queries|client)(\.\w+)?$",
        "sizes": {"warn": 250, "split": 350},
        "co_change_min": 3,
        "bulk_commit": 8,
        "ubiquitous": 3,
        "co_change_exclude": [],
    }
    return cfg, infos


def build_profile(hub, repos, others, infos):
    lines = [
        "=" * 80,
        f"PROJECT PROFILE — {hub.name}",
        f"Generated by the feature-kit on {TODAY}. Built once, reused every session;",
        "re-run when a repo is added or moved.",
        "Lines marked CONFIRM were detected — check them. Lines marked ASK must come",
        "from the owner. Fix each and delete the marker; `kit.py doctor` counts them.",
        "=" * 80,
        "",
        "REPOS  (the docs hub is the repo holding docs/)",
    ]
    for r, i in zip(repos, infos):
        hubmark = "  <- docs hub" if r == hub else ""
        lines += [
            f"  {r.name}{hubmark}",
            f"    path       {r}",
            f"    role       CONFIRM: {i['role']}   stack: {', '.join(i['stack']) or 'UNKNOWN'}",
            f"    mainline   {i['mainline']}",
            f"    gates      " + (" · ".join(i["gates"]) if i["gates"] else "UNKNOWN — find them in its README/scripts"),
            f"    committers {i['committers']} in the last 200 commits"
            + ("  (solo — merges are fine)" if i["committers"] <= 1 else "  (shared — recommend PRs)"),
        ]
    if others:
        lines += ["", "OTHER REPOS BESIDE IT (not included — CONFIRM they are not part of this",
                  "project; if one is, add it to docs/graph.config.json \"repos\")"]
        lines += [f"  {o.name}" for o in others]
    backends = [i["name"] for i in infos if i["role"].startswith("backend")]
    clients = [i["name"] for i in infos if not i["role"].startswith("backend")]
    bridge = (f"CONFIRM: the {backends[0]} API — {', '.join(clients)} call it; they do not call each other"
              if backends and clients else "ASK — what do the repos meet at (a backend contract, a shared package, a module boundary)?")
    lines += ["", "BRIDGE  (every cross-repo relationship runs through it)", f"  {bridge}",
              "", "CALL CHAIN  (UI element -> server, per client)"]
    for i in infos:
        if i["role"].startswith("backend"):
            continue
        lines.append(f"  {i['name']}: {i['call_chain'] or 'UNKNOWN — trace one screen to its endpoint and write it here'}")
    lines += [
        "", "DOCS",
        f"  hub        {hub / 'docs'}",
        "  router     docs/README.md   (also the feature registry)",
        "  format     plain-text docs (.txt), STATUS first — docs/_templates/feature.txt",
        "  health     python3 docs/graph_check.py  ->  docs/GRAPH_STATE.txt",
        "", "CONVENTIONS  (fill from the project's instructions on the first run)",
        "  money      ASK — representation (e.g. integer minor units), never floats",
        "  errors     ASK — the API's error envelope",
        "  auth       ASK — auth model; where authorization is enforced",
        "  theming    ASK — tokens / design system entry point",
        "", "SHIP",
    ]
    for i in infos:
        lines.append(f"  {i['name']}: commit as {i['email']}  (CONFIRM)")
    lines += [
        "  attribution   ASK — trailers/footers on commits and PRs (or none)",
        "  deploy        ASK — which branch deploys where, and how (never guess)",
        "",
    ]
    return "\n".join(lines) + "\n"


def fill(template, **kw):
    s = (TEMPLATES / template).read_text()
    for k, v in kw.items():
        s = s.replace("{{" + k + "}}", v)
    return s


def plan(hub):
    """(label, path, generator) for every file dependency, in creation order."""
    d = hub / "docs"
    return [
        ("profile", d / "PROJECT_PROFILE.txt", "profile"),
        ("router", d / "README.md", lambda: fill("docs_README.md", PROJECT=hub.name, DATE=TODAY)),
        ("template", d / "_templates" / "feature.txt", lambda: fill("feature.txt")),
        ("config", d / "graph.config.json", "config"),
        ("checker", d / "graph_check.py", "checker"),
        ("state", d / "GRAPH_STATE.txt", lambda: fill("GRAPH_STATE.txt", DATE=TODAY)),
        ("preferences", d / "design" / "PREFERENCES.txt", lambda: fill("PREFERENCES.txt", DATE=TODAY)),
        ("components", d / "design" / "components.txt", lambda: fill("components.txt", DATE=TODAY)),
    ]


# ── commands ───────────────────────────────────────────────────────────────
def context():
    root = repo_root(Path.cwd())
    if root is None:
        print("feature-kit: not inside a git repository — run it from a project repo")
        sys.exit(2)
    hub = find_hub(root)
    return root, hub


def cmd_doctor():
    root, hub = context()
    d = hub / "docs"
    print(f"feature-kit doctor — repo: {root.name} · docs hub: {hub}")
    missing = 0
    inst = [f for f in INSTRUCTION_FILES if (root / f).exists()]
    print(f"  [{'OK' if inst else 'NOTE':7}] instructions   {', '.join(inst) if inst else 'none (the profile carries the project facts)'}")
    for label, path, _ in plan(hub):
        rel = path.relative_to(hub)
        if not path.exists():
            missing += 1
            print(f"  [MISSING] {label:<14} {rel}")
            continue
        note = ""
        if label == "checker":
            v, k = engine_version(path), engine_version(ENGINE)
            if v is not None and k is not None and v < k:
                note = f"  OUTDATED (v{v} < kit v{k}) — run `kit.py upgrade`"
        if label == "config":
            try:
                json.loads(path.read_text())
            except Exception as e:
                note = f"  INVALID JSON ({e})"
        if label == "profile":
            n = len(PLACEHOLDER.findall(path.read_text()))
            if n:
                note = f"  {n} CONFIRM/ASK/UNKNOWN left to settle"
        print(f"  [{'OK' if not note else 'TODO':7}] {label:<14} {rel}{note}")
    for sub in ("features", "design", "platform"):
        p = d / sub
        if not p.is_dir():
            missing += 1
            print(f"  [MISSING] {'doc home':<14} docs/{sub}/")
    docs_n = len(list((d / "features").glob("**/*.txt"))) if (d / "features").is_dir() else 0
    print(f"  [{'OK' if docs_n else 'EMPTY':7}] {'feature docs':<14} {docs_n} under docs/features/"
          + ("" if docs_n else " — the first /feature run writes the first entry"))
    ledgers = []
    cfgp = d / "graph.config.json"
    if cfgp.exists():
        try:
            for r in json.loads(cfgp.read_text()).get("repos", []):
                base = (d / r["path"]).resolve()
                ledgers += [f"{r['name']}/{p.name}" for p in base.glob("*PARITY*.txt")]
        except Exception:
            pass
    print(f"  [{'OK':7}] {'parity ledgers':<14} {', '.join(ledgers) if ledgers else 'none (created per cross-repo port: kit.py parity-ledger)'}")
    if missing:
        print(f"\n{missing} missing — run: python3 {KIT / 'kit.py'} init")
        return 1
    print("\nAll dependencies present.")
    return 0


def configured_repos(hub):
    """The repos an existing graph.config.json names — the project's own answer,
    which always outranks detection."""
    cfgp = hub / "docs" / "graph.config.json"
    if not cfgp.exists():
        return None
    try:
        rs = json.loads(cfgp.read_text()).get("repos", [])
    except Exception:
        return None
    out = [(hub / "docs" / r["path"]).resolve() for r in rs]
    return [p for p in out if p.is_dir()] or None


def cmd_init(dry=False):
    root, hub = context()
    d = hub / "docs"
    repos, others = detect_repos(hub)
    known = configured_repos(hub)
    if known:
        others = [o for o in others + repos if o.resolve() not in known]
        repos = known
    cfg = infos = None
    created = []
    for sub in ("features", "design", "platform", "_templates"):
        if not (d / sub).is_dir():
            created.append(f"docs/{sub}/")
            if not dry:
                (d / sub).mkdir(parents=True, exist_ok=True)
    for label, path, gen in plan(hub):
        if path.exists():
            continue
        if gen in ("config", "profile") and cfg is None:
            cfg, infos = build_config(hub, repos)
        if gen == "config":
            body = json.dumps(cfg, indent=2) + "\n"
        elif gen == "profile":
            body = build_profile(hub, repos, others, infos)
        elif gen == "checker":
            body = None
        else:
            body = gen()
        created.append(str(path.relative_to(hub)))
        if dry:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if body is None:
            shutil.copy2(ENGINE, path)
        else:
            path.write_text(body)
    mode = "would create" if dry else "created"
    if created:
        print(f"feature-kit init — {mode} in {hub}:")
        for c in created:
            print(f"  + {c}")
        if repos and not dry:
            print("\nRepos in this project (CONFIRM with the owner): " + ", ".join(r.name for r in repos))
            if others:
                print("Beside it, NOT included: " + ", ".join(o.name for o in others))
            print("Settle the CONFIRM/ASK lines in docs/PROJECT_PROFILE.txt before relying on it.")
    else:
        print("feature-kit init — nothing to create; every dependency exists.")
    return 0


def cmd_upgrade():
    _, hub = context()
    dst = hub / "docs" / "graph_check.py"
    if not dst.exists():
        print("No checker yet — run `kit.py init`.")
        return 1
    v, k = engine_version(dst), engine_version(ENGINE)
    if v is not None and k is not None and v >= k:
        print(f"Checker is current (v{v}).")
        return 0
    shutil.copy2(ENGINE, dst)
    print(f"Checker upgraded v{v} -> v{k} ({dst}). Config untouched. Re-run `kit.py check` "
          "and compare with the last run before trusting a changed count.")
    return 0


def cmd_check():
    _, hub = context()
    p = hub / "docs" / "graph_check.py"
    if not p.exists():
        print("No checker yet — run `kit.py init`.")
        return 1
    return subprocess.call([sys.executable, str(p)])


def cmd_parity_ledger(args):
    if len(args) < 2 or "--source" not in args:
        print('usage: kit.py parity-ledger <target-repo-path> "<title>" --source <source repo name>')
        return 2
    target = Path(args[0]).resolve()
    title = args[1]
    source = args[args.index("--source") + 1]
    slug = re.sub(r"[^A-Z0-9]+", "_", title.upper()).strip("_")
    out = target / f"{slug}_PARITY.txt"
    if out.exists():
        print(f"Exists: {out} — update it, do not start a second ledger.")
        return 0
    out.write_text(fill("PARITY_LEDGER.txt", TITLE=title.upper(), SOURCE=source,
                        TARGET=target.name, DATE=TODAY))
    print(f"Created {out}. Fill §0 (the translation map) on the first port.")
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "doctor"
    if cmd == "doctor":
        return cmd_doctor()
    if cmd == "init":
        return cmd_init(dry="--dry-run" in argv)
    if cmd == "upgrade":
        return cmd_upgrade()
    if cmd == "check":
        return cmd_check()
    if cmd == "parity-ledger":
        return cmd_parity_ledger(argv[2:])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
