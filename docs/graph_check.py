#!/usr/bin/env python3
"""Compute the docs graph's health from the docs and from git. Prints findings
only — it never edits a doc.

    python3 graph_check.py            (from anywhere; it finds its own folder)

GENERIC. Everything project-specific — the repos, where docs live, which source
folders and file types exist, how code reaches an endpoint — comes from
graph.config.json NEXT TO THIS FILE. The feature-kit (~/.claude/feature-kit)
generates both for a new project and upgrades this file in place; the config is
the project's own and is never overwritten.

What it checks, and why each one is here rather than left to judgement:

  ONE-WAY     an edge written on one side only. Invisible from the other end,
              which is the whole failure the bidirectional rule prevents.
  DANGLING    an edge naming a file that does not exist — usually a rename or a
              split that did not carry its edges.
  STALE       the code a doc CITES has been committed to since the doc was last
              verified. Computed from git, not guessed.
  NO MARKER   no `Last verified` line at all. Unknown, not fresh.
  OVERSIZED   past the split threshold (config: sizes.split).
  ORPHAN      a feature doc with no edges in either direction.
  CO-CHANGE   two docs that keep being committed together but declare no edge —
              a missing edge with evidence.
  UNCITED     a doc citing no resolvable source path. The STALE check cannot see
              it, so it is a blind spot worth naming.
  UNMERGED    a branch carrying commits the mainline does not have, in any repo;
              also a repo checked out somewhere other than the mainline.
  UNCOMMITTED code a doc cites has uncommitted changes. STALE reads commit
              dates, so work in the tree is invisible to it until it lands.
  PARITY      a `PARITY: <path>` provenance marker (left by /copy-adapt) whose
              source no longer exists, or whose copy and source are owned by
              different docs that declare no copied-from/copied-to edge.
  PARITY, COPY UNCITED
              a marked copy that no doc cites — findable from code, not docs.
  SHARED CONTRACT
              two docs whose code reaches the SAME endpoint constant — directly,
              or one hop through a module it imports — with no edge between
              them. Derived from code; a DATA change to that endpoint reaches both.

Exit codes: 0 ran (findings or not) · 2 found no docs (never a false all-clear)
· 3 no/invalid config.
"""
import datetime
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

KIT_VERSION = 3  # bumped by the feature-kit when this engine changes

EDGE_KINDS = ("depends-on", "consumed-by", "shares-data-with", "copied-from", "copied-to")
INVERSE = {
    "depends-on": "consumed-by", "consumed-by": "depends-on",
    "copied-from": "copied-to", "copied-to": "copied-from",
    "shares-data-with": "shares-data-with",
}
EDGE = re.compile(r"^(" + "|".join(EDGE_KINDS) + r")\s+(\S+)")
VERIFIED = re.compile(r"Last verified:\s*(\d{4}-\d{2}-\d{2})")

DEFAULTS = {
    "doc_roots": ["features", "platform", "design"],
    "doc_glob": "**/*.txt",
    "index_names": ["README.txt", "README.md"],
    # Logs, not features: never an orphan, never expected to cite code.
    "meta_docs": ["PREFERENCES.txt"],
    "features_root": "features",
    "design_root": "design",
    "state_file": "GRAPH_STATE.txt",
    "mainline": "main",
    "repos": [],
    "source_dirs": ["lib", "internal", "src", "test", "cmd"],
    "prefix_dirs": ["lib", "internal"],
    "marker_dirs": ["lib", "src", "internal", "cmd"],
    "extensions": ["dart", "go", "ts", "tsx"],
    "generated_markers": [".g.", ".freezed."],
    "endpoint_refs": {},
    "imports": {},
    "import_roots": {},
    "module_hop": r"(repository|_api|/api|queries)(\.dart)?$",
    "sizes": {"warn": 250, "split": 350},
    "co_change_min": 3,
    "bulk_commit": 8,
    "ubiquitous": 3,
    "co_change_exclude": [],
}


def load_config(here):
    p = here / "graph.config.json"
    if not p.exists():
        print(f"graph_check: no graph.config.json next to {here} — run "
              "`python3 ~/.claude/feature-kit/kit.py init` to generate one")
        sys.exit(3)
    try:
        raw = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        print(f"graph_check: graph.config.json is not valid JSON ({e})")
        sys.exit(3)
    cfg = {**DEFAULTS, **raw}
    cfg["sizes"] = {**DEFAULTS["sizes"], **raw.get("sizes", {})}
    if not cfg["repos"]:
        print("graph_check: graph.config.json lists no repos")
        sys.exit(3)
    return cfg


class Graph:
    def __init__(self, cfg):
        self.cfg = cfg
        # base (path relative to the docs folder) -> repo name
        self.repos = {r["path"]: r["name"] for r in cfg["repos"]}
        # Longest extension first: with `ts|tsx`, every .tsx citation matched as
        # .ts — a file that does not exist — so every web path a doc cited was
        # silently dropped. Route groups "(app)" and segments "[id]" are legal.
        exts = "|".join(sorted((re.escape(e) for e in cfg["extensions"]), key=len, reverse=True))
        src = "|".join(re.escape(d) for d in cfg["source_dirs"])
        pre = "|".join(re.escape(d) for d in cfg["prefix_dirs"])
        self.fullpath = re.compile(rf"(?:{src})/[A-Za-z0-9_/.()\[\]-]+\.(?:{exts})(?![A-Za-z])")
        self.prefix = re.compile(rf"(?:{pre})/[A-Za-z0-9_/.-]*/") if pre else None
        self.tail = re.compile(rf"(?:^|\s)((?:[a-z0-9_]+/)*[a-z0-9_]+\.(?:{exts}))(?![A-Za-z])")
        self.parity_mark = re.compile(
            rf"PARITY:\s*((?:[A-Za-z0-9_.()\[\]-]+/)*[A-Za-z0-9_.()\[\]-]+\.(?:{exts}))(?![A-Za-z])")
        self.source_ext = tuple("." + e for e in cfg["extensions"])
        self.endpoint_refs = {k: re.compile(v) for k, v in cfg["endpoint_refs"].items()}
        self.imports = {k: re.compile(v, re.M) for k, v in cfg["imports"].items()}
        self.module_hop = re.compile(cfg["module_hop"]) if cfg["module_hop"] else None
        self._endpoint_memo = {}

    # ── docs ────────────────────────────────────────────────────────────────
    def docs(self):
        return sorted(p for r in self.cfg["doc_roots"] for p in Path(r).glob(self.cfg["doc_glob"]))

    def is_index(self, p):
        return p.name in self.cfg["index_names"]

    def is_meta(self, p):
        return self.is_index(p) or p.name in self.cfg["meta_docs"]

    def cited_paths(self, text, window=6):
        """Every source path a doc names, resolved against the repos.

        Docs abbreviate: a directory is named once and the files under it follow
        as bare tails ("internal/apps/payment/" then "model/model.go"). A tail is
        paired ONLY with a prefix seen in the last few lines — pairing it with any
        prefix in the file invents paths that were never cited.

        A path written with its repo in front ("repo/lib/x.dart") resolves in THAT
        repo, so a path two repos share is credited to the one the doc named.

        Returns sorted (rel, base) pairs.
        """
        by_name = {name: base for base, name in self.repos.items()}
        found, pinned, recent = set(), set(), []
        for line in text.splitlines():
            for m in self.fullpath.finditer(line):
                head = re.search(r"([A-Za-z0-9_-]+)/$", line[:m.start()])
                if head and head.group(1) in by_name:
                    pinned.add((m.group(0), by_name[head.group(1)]))
                else:
                    found.add(m.group(0))
            pres = self.prefix.findall(line) if self.prefix else []
            for m in self.tail.finditer(line):
                tail = m.group(1)
                if any(tail in f for f in found) or any(tail in f for f, _ in pinned):
                    continue
                for p in (pres + recent):
                    found.add(p + tail)
                    break
            if pres:
                recent = (pres + recent)[:window]
        out = {(rel, base) for rel, base in pinned if os.path.exists(os.path.join(base, rel))}
        for rel in found:
            for base in self.repos:
                if os.path.exists(os.path.join(base, rel)):
                    out.add((rel, base))
                    break
        return sorted(out)

    # ── git ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _git(base, *args, timeout=20):
        try:
            return subprocess.run(["git", "-C", base, *args], capture_output=True,
                                  text=True, timeout=timeout).stdout.strip()
        except Exception:
            return ""

    def last_commit(self, base, rel):
        return self._git(base, "log", "-1", "--format=%cs", "--", rel) or None

    def branch_state(self):
        main = self.cfg["mainline"]
        out = []
        for base, name in self.repos.items():
            if not os.path.isdir(os.path.join(base, ".git")):
                continue
            cur = self._git(base, "rev-parse", "--abbrev-ref", "HEAD")
            for b in self._git(base, "for-each-ref", "--format=%(refname:short)", "refs/heads/").split():
                if b == main:
                    continue
                ahead = self._git(base, "rev-list", "--count", f"{main}..{b}")
                if not ahead or ahead == "0":
                    continue
                last = self._git(base, "log", "-1", "--format=%cs", b)
                behind = self._git(base, "rev-list", "--count", f"{b}..{main}")
                idle = ""
                try:
                    d = (datetime.date.today() - datetime.date.fromisoformat(last)).days
                    idle = f", idle {d}d" if d >= 7 else ", active"
                except Exception:
                    pass
                note = f"{name}: '{b}' is {ahead} ahead / {behind} behind {main} (last {last}{idle})"
                if behind.isdigit() and int(behind) > 50:
                    note += "\n      RISK: far behind as well — reconcile before merging, not after"
                elif idle.endswith("active"):
                    note += "\n      IN PROGRESS — do not prompt to merge; it is being worked on"
                else:
                    note += "\n      LOOKS DONE AND FORGOTTEN — a merge/PR candidate once its gates pass"
                out.append(note + "\n      (work the docs cannot see until it lands)")
            authors = {a for a in self._git(base, "log", "-200", "--format=%ae").split() if a}
            if len(authors) > 1:
                out.append(f"{name}: {len(authors)} committer identities in the last 200 commits "
                           f"— recommend a PULL REQUEST, never a direct merge to {main}")
            if cur and cur != main:
                out.append(f"{name}: checked out on '{cur}', not {main} — verification "
                           f"this session describes THAT branch's code")
        return out

    def dirty_paths(self):
        out = {}
        for base in self.repos:
            if not os.path.isdir(os.path.join(base, ".git")):
                continue
            r = self._git(base, "status", "--porcelain", "--untracked-files=all", timeout=30)
            out[base] = {line[3:].split(" -> ")[-1].strip('"') for line in r.splitlines() if len(line) > 3}
        return out

    def co_change(self):
        pairs = defaultdict(int)
        docs_dir = Path.cwd()
        hub = self._git(str(docs_dir), "rev-parse", "--show-toplevel")
        if not hub:
            return pairs
        rel_docs = os.path.relpath(docs_dir, hub)
        out = self._git(hub, "log", "--format=@%h", "--name-only", "--", rel_docs, timeout=60)
        ext = Path(self.cfg["doc_glob"]).suffix or ".txt"
        excl = self.cfg["co_change_exclude"]
        batch = []
        for line in out.splitlines() + ["@end"]:
            if line.startswith("@"):
                # A commit touching many docs at once (a restructure, a marker
                # sweep) says nothing about which docs belong together.
                if len(batch) > self.cfg["bulk_commit"]:
                    batch = []
                for i in range(len(batch)):
                    for j in range(i + 1, len(batch)):
                        pairs[tuple(sorted((batch[i], batch[j])))] += 1
                batch = []
            elif line.endswith(ext) and not any(x in line for x in excl):
                batch.append(os.path.basename(line))
        return pairs

    # ── PARITY markers ──────────────────────────────────────────────────────
    def resolve_marker(self, target, base):
        head, _, rest = target.partition("/")
        for b, name in self.repos.items():
            if head == name and rest:
                return (b, rest) if os.path.exists(os.path.join(b, rest)) else None
        return (base, target) if os.path.exists(os.path.join(base, target)) else None

    def parity_markers(self):
        pairs = []
        gen = self.cfg["generated_markers"]
        for base in self.repos:
            for sub in self.cfg["marker_dirs"]:
                root = Path(base) / sub
                if not root.is_dir():
                    continue
                for f in root.rglob("*"):
                    if f.suffix not in self.source_ext or any(g in f.name for g in gen):
                        continue
                    if "node_modules" in f.parts:
                        continue
                    try:
                        body = f.read_text(errors="ignore")
                    except Exception:
                        continue
                    copy = (base, str(f.relative_to(base)))
                    for raw in dict.fromkeys(m.group(1) for m in self.parity_mark.finditer(body)):
                        pairs.append((copy, self.resolve_marker(raw, base), raw))
        return pairs

    # ── endpoints (the call chain's last hop) ───────────────────────────────
    def _module_for(self, base, spec, frm):
        roots = self.cfg["import_roots"]
        if spec.startswith("dart:"):
            return None
        cand = None
        for pfx, root in roots.items():
            if spec.startswith(pfx):
                rest = spec[len(pfx):]
                if pfx == "package:":  # package:<name>/<path> -> <root>/<path>
                    rest = rest.partition("/")[2]
                cand = Path(base) / root / rest
                break
        if cand is None:
            if not spec.startswith("."):
                return None
            cand = (Path(base) / frm).parent / spec
        for c in (cand, cand.with_suffix(".ts"), cand.with_suffix(".tsx"), Path(str(cand) + ".ts")):
            if c.is_file():
                return c
        return None

    def endpoints_of(self, base, rel):
        key = (base, rel)
        if key in self._endpoint_memo:
            return self._endpoint_memo[key]
        f = Path(base) / rel
        rx = self.endpoint_refs.get(f.suffix)
        found = set()
        if rx and f.is_file():
            body = f.read_text(errors="ignore")
            name = self.repos[base]
            found |= {(name, n) for n in rx.findall(body)}
            imp = self.imports.get(f.suffix)
            for spec in (imp.findall(body) if imp else []):
                if self.module_hop and not self.module_hop.search(spec):
                    continue
                mod = self._module_for(base, spec, rel)
                if mod is not None:
                    found |= {(name, n) for n in rx.findall(mod.read_text(errors="ignore"))}
        self._endpoint_memo[key] = found
        return found


def main():
    here = Path(os.path.dirname(os.path.abspath(__file__)))
    # Every path is relative to the docs folder. Run from anywhere else it used
    # to find nothing and print an all-clear that was a failure to look.
    os.chdir(here)
    cfg = load_config(here)
    g = Graph(cfg)
    all_docs = g.docs()
    if not all_docs:
        print("graph_check: found NO docs under " + ", ".join(cfg["doc_roots"]) +
              " — refusing to report a clean graph")
        return 2
    text = {p: p.read_text() for p in all_docs}
    findings = defaultdict(list)
    feats = cfg["features_root"]

    # edges
    has_edge = set()
    for p in all_docs:
        for line in text[p].splitlines():
            m = EDGE.match(line)
            if not m:
                continue
            kind, target = m.groups()
            has_edge.add(p)
            tp = (p.parent / target).resolve()
            if not tp.exists():
                findings["DANGLING"].append(f"{p} -> {target}")
                continue
            inv = INVERSE[kind]
            if not re.search(rf"^{inv}\s+\S*{re.escape(p.name)}", tp.read_text(), re.M):
                findings["ONE-WAY"].append(f"{tp.name} needs '{inv} … {p.name}'  (declared by {p})")

    # verification vs git
    cited = {p: g.cited_paths(text[p]) for p in all_docs}
    for p in all_docs:
        m = VERIFIED.search(text[p])
        paths = cited[p]
        if not m:
            findings["NO MARKER"].append(str(p))
            continue
        if not paths:
            if not g.is_meta(p):
                findings["UNCITED"].append(f"{p} — no resolvable source path, so staleness is unknowable")
            continue
        vd, newest, where = m.group(1), None, None
        for rel, base in paths:
            d = g.last_commit(base, rel)
            if d and (newest is None or d > newest):
                newest, where = d, rel
        if newest and newest > vd:
            findings["STALE"].append(f"{p} — verified {vd}, but {where} was committed {newest}")

    # size
    warn, split = cfg["sizes"]["warn"], cfg["sizes"]["split"]
    for p in all_docs:
        n = len(text[p].splitlines())
        if n > split:
            findings["OVERSIZED"].append(f"{p} — {n} lines, past the {split} split threshold")
        elif n > warn:
            findings["APPROACHING SIZE"].append(f"{p} — {n} lines (warn at {warn})")

    # orphans
    for p in all_docs:
        if p not in has_edge and not g.is_meta(p):
            findings["ORPHAN"].append(f"{p} — no edges in either direction")

    # co-change without an edge
    by_name = {p.name: p for p in all_docs}
    for (a, b), n in sorted(g.co_change().items(), key=lambda kv: -kv[1]):
        if n < cfg["co_change_min"] or a not in by_name or b not in by_name:
            continue
        if a in cfg["index_names"] or b in cfg["index_names"]:
            continue
        pa, pb = by_name[a], by_name[b]
        if re.search(re.escape(b), text[pa]) or re.search(re.escape(a), text[pb]):
            continue
        findings["CO-CHANGE, NO EDGE"].append(f"{a} + {b} — committed together {n}×, no edge declared")

    # uncommitted code under a doc
    dirty = g.dirty_paths()
    for p in all_docs:
        hits = sorted(rel for rel, base in cited[p] if rel in dirty.get(base, ()))
        if hits:
            more = f" (+{len(hits) - 3} more)" if len(hits) > 3 else ""
            findings["UNCOMMITTED"].append(
                f"{p} — cites uncommitted {', '.join(hits[:3])}{more}; re-verify it in the same commit")

    owners = defaultdict(set)
    for p in all_docs:
        for rel, base in cited[p]:
            owners[(base, rel)].add(p)

    def edge_between(a, b, kinds):
        for x, y in ((a, b), (b, a)):
            for line in text[x].splitlines():
                m = EDGE.match(line)
                if m and m.group(1) in kinds and (x.parent / m.group(2)).resolve() == y.resolve():
                    return True
        return False

    # provenance markers vs declared copy edges
    for copy, source, raw in g.parity_markers():
        where = f"{g.repos[copy[0]]}/{copy[1]}"
        if source is None:
            findings["PARITY"].append(f"{where} — PARITY names {raw}, which does not exist")
            continue
        a, b = owners.get(copy, set()), owners.get(source, set())
        if not a:
            findings["PARITY, COPY UNCITED"].append(
                f"{where} copies {raw}; no doc cites the copy"
                + (f" (source owned by {sorted(y.name for y in b)})" if b else ""))
            continue
        if not b or a & b:
            continue
        if not any(edge_between(x, y, {"copied-from", "copied-to"}) for x in a for y in b):
            findings["PARITY"].append(
                f"{where} copies {raw}, but {sorted(x.name for x in a)} and "
                f"{sorted(y.name for y in b)} declare no copied-from/copied-to edge")

    # derived: two docs reaching the same endpoint, with no edge at all
    if g.endpoint_refs:
        reach = defaultdict(set)
        for p in all_docs:
            if g.is_index(p) or p.parts[0] == cfg["design_root"]:
                continue
            for rel, base in cited[p]:
                reach[p] |= g.endpoints_of(base, rel)
        freq = defaultdict(int)
        for p in reach:
            for e in reach[p]:
                freq[e] += 1
        for p in reach:
            reach[p] = {e for e in reach[p] if freq[e] <= cfg["ubiquitous"]}
        deps = defaultdict(set)
        for p in all_docs:
            for line in text[p].splitlines():
                m = EDGE.match(line)
                if m and m.group(1) == "depends-on":
                    t = (p.parent / m.group(2)).resolve()
                    if f"/{feats}/" in str(t):
                        deps[p].add(t)
        ds = [p for p in all_docs if reach[p]]
        for i in range(len(ds)):
            for j in range(i + 1, len(ds)):
                a, b = ds[i], ds[j]
                shared = reach[a] & reach[b]
                if not shared or edge_between(a, b, set(EDGE_KINDS)):
                    continue
                if deps[a] & deps[b]:
                    continue
                names = sorted(n for _, n in shared)
                more = f" (+{len(names) - 3} more)" if len(names) > 3 else ""
                findings["SHARED CONTRACT, NO EDGE"].append(
                    f"{a.name} + {b.name} — both reach {', '.join(names[:3])}{more}")

    for line in g.branch_state():
        findings["UNMERGED BRANCH"].append(line)

    order = ["UNMERGED BRANCH", "DANGLING", "ONE-WAY", "STALE", "PARITY", "UNCOMMITTED",
             "OVERSIZED", "NO MARKER", "CO-CHANGE, NO EDGE", "SHARED CONTRACT, NO EDGE",
             "PARITY, COPY UNCITED", "ORPHAN", "APPROACHING SIZE", "UNCITED"]
    total = 0
    for k in order:
        if not findings[k]:
            continue
        print(f"\n{k}  ({len(findings[k])})")
        for line in findings[k]:
            print(f"  {line}")
        total += len(findings[k])
    print(f"\n{len(all_docs)} docs · {total} findings")
    print("Blocking classes are UNMERGED BRANCH, DANGLING, ONE-WAY and STALE "
          f"— see {cfg['state_file']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
