---
description: Run feature work, or any task, under a general execution checklist — orient in the active repo, tier-1 standards, per-point pre-flight ritual, then wait for go
argument-hint: <paste the feature / task instruction>
---

You are implementing the following under the **General Execution Checklist**:

> $ARGUMENTS

Apply the tier-1, primary-source standards below. **Every project-specific
detail — stack, docs location, tokens, units, branches, commit identity, gate
commands — is discovered from the active repo, never assumed.** Where a standard
and a repo convention collide, the repo convention wins and you flag it.

## Step 0.0 — The kit: make sure everything this skill relies on exists

This skill leans on a set of project files — a profile, a docs router that
doubles as the feature registry, the doc homes and template, a graph checker
with its config, the graph state file, a preferences log, a shared-components
doc. **None of that may be assumed.** The feature-kit checks for each and
generates whatever a project lacks. Run it first, every time:

```
python3 ~/.claude/feature-kit/kit.py doctor
```

- **Anything `[MISSING]`** → `python3 ~/.claude/feature-kit/kit.py init`. It
  creates only what is absent and **never overwrites** a file. Then, in the
  pre-flight, show what was created and the repo list it detected — the one
  thing a tool cannot know is which sibling folders are really part of this
  project, so that list is **confirmed with the user, never assumed**.
- **Profile `[TODO]`** (CONFIRM / ASK / UNKNOWN lines left in
  `docs/PROJECT_PROFILE.txt`) → settle every one you can from the project's own
  instructions and code while orienting, and delete its marker. What no file
  answers (commit attribution, the deploy path) is ASKED — in the pre-flight if
  this work needs it, otherwise at ship time. Never guess one.
- **Checker `OUTDATED`** → `kit.py upgrade`, then re-run the check and compare
  the count with the last run before trusting a change.
- **The kit itself missing** (`~/.claude/feature-kit/` absent) → say so plainly
  and work without it: every check it would run is done by reading.

`kit.py check` runs the project's graph check from any of its repos; the kit
finds the docs hub itself.

## Step 0 — Orient in THIS repo (mandatory, before any code)

Do not carry conventions across from another project. Establish, for the repo you
are actually in:

1. **Read the project's own instructions** — `CLAUDE.md`, `AGENTS.md`, or
   `README.md` at the repo root. These outrank anything in this checklist.
2. **Find the knowledge base.** Look for `docs/README.md` (or an index the root
   doc points to). If it exists, treat it as a router: read the router, match the
   request against it to find where the work starts, and read that entry in full.
   Then **walk outward from it** — see *The feature graph* below — instead of
   guessing which neighbours matter. If there is no docs tree, say so — that is a
   real finding and it means you are working without written precedent.
3. **Check the knowledge base's own health BEFORE trusting it.** Read the state
   file (`docs/GRAPH_STATE.txt`) and run `kit.py check`, and say what they report
   for the area you are about to work in.
   - A **BLOCK** covering this area means the docs here contradict the code, so
     building on them produces wrong work. **Fix it first, or override
     explicitly** — naming the block and why it does not apply to this change,
     and recording that override in the file. An override nobody wrote down
     happened by accident.
   - A **WARN** means read the code rather than the prose for anything
     load-bearing, and re-verify while you are in there.
   - **Nothing listed is not the same as verified.** A checker can only see what
     the docs let it see; say which it is.
   Re-run the check rather than trusting the file's own timestamp — that is the
   one claim in it that nothing else validates.
4. **Check what branch every repo is on, before trusting any of it.** This is
   cheap and it invalidates everything above when it goes wrong:
   - **Is anything ahead of the mainline?** A feature sitting unmerged on a
     branch is a feature the docs cannot describe and no checker can see. You
     would build a second one without knowing the first exists.
   - **Is each repo checked out where this work belongs?** Verifying against one
     branch and shipping to another means "verified" described code the user
     will never run.
   - **Say which branch each claim came from** when repos disagree. "The code
     says X" is incomplete if another branch says Y.
   A project with a branch-per-vertical rule has a second failure here: branches
   that are only ever BEHIND mean the rule is not being followed and the
   mainline is the real source of truth. Report that rather than assuming the
   written rule describes reality.

   **If an unmerged branch overlaps the area you are about to touch, say so
   before building.** That is the one case where this stops work: you would
   otherwise build on top of something that is about to land, or build a second
   copy of it.
5. **Check what is uncommitted in every repo** (`git status --porcelain`). The
   same blindness as an unmerged branch, one level down: a staleness check
   reads commit dates, so work sitting in the tree is invisible to it — a doc
   can read clean while the code under it is mid-change. Name any uncommitted
   file in the area you are touching, and whose it is if you can tell (a
   previous session's unfinished work, the user's own edits). **Never fold
   someone else's uncommitted edit into your change, or "tidy" it away** —
   leave it exactly as found and say that you did.

### When to suggest landing a branch

Work that is finished and sitting unmerged is invisible — to the docs, to any
checker, and to whoever builds next. But a skill that nags about every old
branch gets ignored within a week, so only one signature is worth raising:

> **ahead of the mainline · its gates pass · nobody has touched it in a while**

That combination means *done and forgotten*, which is the only case where the
prompt tells someone something they did not already know.

- **Ahead and still being committed to → say nothing.** It is in progress.
- **Ahead and also far behind → report it as a RISK, not an invitation.** Five
  ahead and two hundred behind is a reconciliation growing, not a ready feature,
  and "merge this" is the wrong advice.
- **Age alone is never maturity.** An abandoned branch is old too.

**Merge or pull request? Detect it — never assume, and never default to merge.**
More than one committer identity in recent history, a protected mainline, or an
existing PR habit all mean **recommend a PR**. Telling a contributor to push
straight to main bypasses the review their team depends on, and that is a worse
outcome than staying quiet. Only when it is clearly a solo repo with no
protection is offering the merge the right call.

**Raise it, never do it.** A merge, a push and an opened PR are all outward
facing and awkward to undo — they need an explicit go, every time. And raise it
in the right place: **at ship time**, unless the branch overlaps the work, in
which case it belongs in the pre-flight. Do not interrupt a feature for branch
housekeeping.
6. **Identify the surfaces this work touches** and the rulebook for each:
   - Detect the stack from manifests — `package.json`, `pubspec.yaml`, `go.mod`,
     `pyproject.toml`/`requirements.txt`, `Cargo.toml`.
   - For each, name the governing authority you will actually apply (e.g. the
     official architecture guide for that framework, the language's idiom guide).
   - **Pin versions from the lockfile, not memory.** A major version you assumed
     is how breaking changes get shipped. If a framework's major version has
     breaking changes, read its bundled docs before writing code for it.
7. **Note the project's own conventions** so you can obey them: money/unit
   representation, error envelope, naming, folder layout, theme tokens, auth model.
8. **Load the project profile** — `docs/PROJECT_PROFILE.txt`. The kit generates
   it on the first run (Step 0.0); this step settles what it could not detect.

### The project profile (built once, reused every session)

A project is usually several repos. The profile is the short record of what they
are, so it is established once instead of re-derived every session. `kit.py init`
writes the detected parts — repos, roles, stacks, gates, mainline, commit
identity, the likely bridge and call chain — marked CONFIRM; what it cannot
detect is marked ASK. Settling them is this step:

- **Detect, then confirm.** Scan the parent directory for sibling repos carrying
  manifests. Show the list and ask if it is the project — asking "how many repos"
  when you can look is just making the user type.
- **Classify each repo:** backend · client · web · shared library. This decides
  how changes travel between them.
- **Name the bridge.** Clients usually do not call each other; they meet at
  something — a backend contract, a shared package, a module boundary. Say which
  it is here. **Every cross-repo relationship runs through that bridge.**
- **Record the call chain** — how this stack gets from a UI element to the
  server. In one project it is screen → repository → endpoint constant; in
  another it is a hook → a client module. You need it to follow a change across
  a repo boundary, and it is stack-specific, so find it rather than assume it.
- **Write it down** in `docs/PROJECT_PROFILE.txt` — repos, paths, roles, the
  bridge, the call chain, conventions, and the SHIP section (identity,
  attribution, deploy). When a repo is added or moved, update the profile AND
  the `repos` list in `docs/graph.config.json` — the checker reads that list,
  and it outranks detection.

Answer in the pre-flight, out loud:

- **New work, or an addition to something that exists?** An addition inherits that
  thing's decisions, vocabulary and invariants. Treating it as new is how a second
  way of doing the same thing gets built.
- **Which invariants apply?** Quote them, with their source. These are traps that
  already cost someone time.

**Never describe code or a feature from memory.** If a doc exists, open it and
quote it. If nothing exists for this area, say "there is nothing on X" — that is a
real answer. Inventing a description of code you have not read is the failure this
step exists to prevent.

## The feature graph

Features are not islands. Change one and others are affected, and the expensive
failures are the ones nobody saw coming — a rule quoted in a doc you did not
open, a screen showing the same data in a repo you did not look at.

The graph makes those reachable instead of remembered. **There is no graph file
and no database:** the graph is the project's own docs, each naming its
neighbours, plus what can be computed from the code.

**If the knowledge base declares no edges, say so and work as before** — read the
router, open what the work touches, and name it as a gap. A graph you invent on
the spot is worse than none.

### Three kinds of node

| Node | What it is |
|---|---|
| **Feature** | one doc — the unit the user talks about |
| **Component** | a screen, module, command — whatever this project's code is organised into |
| **Contract** | an endpoint, event, or shared model — **the only node that spans repos** |

### Edges: declare two, compute the rest

**Declared** — written into the doc's `Related` section, one clause saying what
flows across:

- `depends-on` ⇄ `consumed-by` — one relies on the other's behaviour
- `shares-data-with` — symmetric; the same data, different purposes
- `copied-from` ⇄ `copied-to` — one was built by adapting the other

**An edge is written in both directions in the same pass.** A one-way edge is
invisible to anyone starting from the other end, which defeats the point.

**Derived** — recomputed each time, so they cannot go stale. Prefer these:

- a Feature *owns* Components — from the doc's own "where it lives"
- a Component *calls* a Contract — follow the profile's call chain
- two Components *render the same Contract* — they reach the same endpoint
- `copied-from` at component level — from the provenance marker `/copy-adapt`
  leaves behind
- a Component *uses* a shared helper that **carries a rule** — validation,
  formatting, money arithmetic. A mechanical helper is noise; one that encodes
  behaviour makes every caller reachable by a RULE change.
- a Component *uses* translation keys — WORDS changes reach the message bundles
  for **every** language, not only the one you were reading.
- a persisted model *has* migrations — a DATA change to something already stored
  reaches its backfills, and the API contract document, or it ships as a silent
  schema mismatch.

These last three are not guesses: each was found by replaying real changes that
had to be propagated by hand, and each had been missed.

Label every edge with its confidence, and never present a guess as a fact:
**certain** (derived from code) · **stated** (someone wrote it) · **suspected**
(inferred, e.g. two docs that keep changing in the same commit).

### Five kinds of change

Classify what you are doing — it is what decides how far the change travels.
Some kinds are empty in some projects; a backend has no LOOK, a library has no
ACCESS. Skip the empty ones rather than forcing them.

| Kind | What changed |
|---|---|
| **LOOK** | how something is displayed |
| **DATA** | the fields or format being passed around |
| **RULE** | how something behaves — an invariant, an ordering, a window |
| **ACCESS** | who is permitted to do it |
| **WORDS** | naming, labels, copy, translation keys |

### What each edge carries

A change travels only along edges that conduct it. **This is the stopping rule —
not a depth limit.**

| | renders-same-contract | copied-from | calls | depends-on | shares-data-with |
|---|---|---|---|---|---|
| **LOOK** | carries | carries | blocks | blocks | blocks |
| **DATA** | carries | blocks | carries | carries | carries |
| **RULE** | blocks | *test* | blocks | carries | carries |
| **ACCESS** | blocks | carries | carries | carries | blocks |
| **WORDS** | carries | carries | blocks | blocks | carries |

***test*** — a RULE crossing a copy may or may not have been inherited. Settle it
by reading: **does that doc state the rule as one of its own invariants?** Quoted
means affected; absent means not.

**Classify per changed file, not per change.** A real change is usually several
kinds at once, and lumping them makes everything conduct everything. The widget
you edited is a LOOK change and walks from there; the model you edited is a DATA
change and walks from there. Separate small walks, each pruning on its own.

### The walk

```
put the changed node on the list
while the list is not empty:
    take a node off it
    for each edge leaving it:
        does this change kind travel along this edge?
        no  -> record the node and why it was ruled out; do not follow it
        yes -> if the neighbour is newly reached, mark it and add it to the list
```

Run it **inward before building** (what constrains me) and **outward after
building** (what did I disturb). Same table both directions.

- **When unsure, treat it as reached.** A false positive costs a glance; a miss
  costs a rebuilt feature.
- **Stop at ~10 nodes** and say so. That ceiling is not a safety mechanism — the
  walk terminates on its own. It is a signal that **the change is architectural
  rather than local**, which is worth knowing before going further.
- **Report what was ruled out, by name.** The blocked set is how the user sees
  you actually checked rather than did not look.

### Report the walk, every time

Print it in the pre-flight even when nothing was followed, so it is visible that
the step ran:

```
WALK  start: <node>  (matched: "<the user's words>")
  ├─ <neighbour>   CARRIES   <what reaches it>
  │   └─ <deeper>  RULED OUT <why>
  └─ <neighbour>   RULED OUT <why>
  reached 4 · ruled out 3 · confidence: 2 certain, 2 stated
```

**The user is reading this to catch a wrong call before you build on it.** Make
the reasons specific enough to argue with.

## The standards (apply throughout)

1. **Reuse & copy-adapt** — search the repo for the closest existing thing before
   writing anything new; reuse bottom-up (shared primitives → composed widgets →
   feature code). Use `/copy-adapt` to port it, changing only what the new domain
   forces. DRY · single source of truth · YAGNI · rule of three.
2. **Architecture** — SOLID · Clean Architecture · 12-Factor · separation of
   concerns. For APIs: consistent error envelope, pagination, versioning,
   idempotency, optimistic concurrency with a graceful conflict path. **Money and
   physical quantities use the project's declared representation** — find it and
   obey it; never invent a second one, and never use floats for money.
3. **Design (any UI work)** — read the project's design docs/tokens first rather
   than reinventing. Universals: tokens only, never raw hex or ad-hoc sizes ·
   every theme the project supports, always · reserve low-contrast greys for
   labels, never for a figure that matters · follow the project's established
   action placement instead of introducing a new pattern. Authorities: the
   project's own design system first, then Material/HIG, Refactoring UI.
4. **Information clarity & states** — never truncate meaningful data, and never
   compact a figure on a surface whose job is reporting it. Four states on every
   async surface: loading · empty · actionable error with retry · content. **A
   failed fetch must say so, never render nothing.** Disable triggers in flight.
5. **Accessibility — WCAG 2.2 AA** — text contrast ≥ 4.5:1 (large ≥ 3:1),
   non-text/UI ≥ 3:1, targets ≥ 44×44 (min 24×24), focus always visible, respect
   reduced-motion. **Measure, don't eyeball** — compute the ratio against the
   actual background before claiming a colour passes.
6. **Dev quality** — Clean Code · the language's own idiom guide (Effective Go /
   Effective Dart / TS strict / PEP 8 + type hints) · composition over inheritance
   · immutability · explicit typed errors, sanitized at the boundary, never raw
   database or driver errors · exhaustive switches. Test the failure paths and the
   concurrency, not just the happy path.
7. **Security** — OWASP Top 10 for the relevant surface (API / mobile / web).
   **Authorization is enforced server-side on every request** — client-side role
   checks are UX only. Fail-closed · least privilege · validate at the model
   boundary · parameterized/typed queries · no secrets or PII in logs · TLS ·
   secure storage. A new gated action means adding the permission in lockstep with
   the server-side check.
8. **Scope & assumptions** — build exactly what was asked; flag gold-plating
   separately rather than folding it in; state assumptions explicitly. If the work
   spans several repos or surfaces, plan all of them up front.

## Verification discipline (the rule that saves the most time)

**The running system is the authority — not the docs, not the code comments, not
your earlier conclusion in this conversation.**

- Prefer querying the live system over inferring from a source that may be stale.
- When a system publishes its own status, read that instead of re-deriving it
  from a proxy you invented. A threshold you guessed will refuse work the system
  would have allowed.
- A claim you made earlier is not evidence. Re-check it if the situation changed,
  and say plainly when it turns out wrong.
- When something does not behave as expected, instrument it and read the actual
  values before theorising about the cause.

## Step 1 — PRE-FLIGHT RITUAL, then STOP

**Structure the pre-flight PER POINT OF THE REQUEST, not as global buckets.**
Break the request into its constituent decisions (one heading each, named after
*the user's* wording so they recognise it). Under each heading give only the
labels that actually apply — omit any that don't, never pad:

- **Current state** — what exists in code today for this specific point (verified,
  with `file:line`; say "nothing" when nothing).
- **Agreement** — what's right about it, and why. Say so plainly when the user is
  right.
- **Objection** — the risk, conflict or false premise in *this* point. One
  objection per bullet; never lump unrelated objections together.
- **Industry standard** — the named primary source governing *this* point, not a
  generic list.
- **Recommendation** — what to do about this point.

Then close with two short global sections:

- **Overall recommendation** — the one approach you'd take across all points, plus
  the runner-up and why you rejected it.
- **Assumptions** — anything you'd proceed on without asking.

**Size the plan from what the walk reached**, not from how big the request
sounded. The count is already in front of you:

| Reached | Plan |
|---|---|
| 0–2 nodes | local — a few steps, usually one repo |
| 3–6 nodes | staged, naming every repo up front |
| 7+ nodes | **architectural** — plan in phases, and say plainly whether the change should be narrowed instead |

The number is worth more as a warning than as a measurement: something you
described as small reaching eleven nodes is the moment to reconsider its scope,
while no code exists yet.

Rules: verify every "current state" claim against the code before writing it —
never assume, and correct the user's premises (and your own earlier statements)
when the code disagrees. Be concise per bullet: a claim plus a reason, not a
paragraph. Do not lump every objection into the recommendation section.

**Close with the lock-in list.** Before the go, state the decisions this work
commits to — three or four lines, plainly enough that the user can spot one they
disagree with:

> *Locking these in: <decision> · <decision> · <decision>. Anything you want left
> out?*

Only genuine decisions — calls that could reasonably have gone the other way. Not
measurements, not spacing, not naming.

**Then stop and wait for the user's command.** Do not plan further or write code
until they say go.

## Step 2 — On go: execute, then report the gates honestly

After implementing, run the project's definition-of-done gates for the surfaces
you touched and **report exactly what you achieved** — pass, fail or skipped for
each, with the failing output included. Never silently claim done.

Find the gates in the project's `CLAUDE.md`/`README.md` or its manifest scripts.
Typical shapes, to be confirmed against the repo rather than assumed:

| Stack | Usual gates |
|---|---|
| Node/TS | `typecheck` · `lint` · `test` · `build` |
| Flutter | `flutter analyze` · `flutter test` · codegen re-run after annotated edits |
| Go | `go build ./...` · `go vet ./...` · `go test ./...` |
| Python | type check · lint · `pytest` |
| Rust | `cargo check` · `cargo clippy` · `cargo test` |

If the project defines its own, those win.

**Report tersely.** One line per gate, one line per outcome, one line per thing
still owed to the user. A result the user has to dig out of a paragraph is a
result they did not get.

## Step 3 — Propagate: what did this change disturb?

**Run this only when the change could reach anything** — the diff touches a
contract, a shared component, or a file some doc claims as its own. A copy tweak
or an isolated fix gets one line saying so, and nothing more. The pass has to
stay cheaper than the drift it prevents.

Start from the diff across **every** repo the work touched, not just this one.
For each changed file, classify its change kind, then walk outward along the
edges that carry it. Follow the profile's call chain to cross a repo boundary.

Present what you find as a decision list, sorted by consequence:

```
PROPAGATE
  MUST     <node>   <what it shares with the change>
  REVIEW   <node>   <carries it, but has adapted — needs a judgement>
  FLAG     <node>   <the rule test was inconclusive; say what is unclear>
  NOT REACHED (checked)  <node> · <node>   <which edge blocked it>
```

- **Report only. Never edit another feature's code without being told to.** A
  neighbour is sometimes *meant* to differ — a different audience, different
  permissions, a deliberate fork.
- **Anything declined gets written into the doc as a known divergence, with the
  reason and the date.** Otherwise the next session re-raises it, or worse, reads
  it as a bug and "fixes" a deliberate decision.
- A decline **demotes, never suppresses.** It must not silently remove that
  neighbour from future reports — one wrong "no" would blind the system
  permanently, and nobody would ever find out.

## Step 4 — Update the docs (after it works, before reporting done)

Write up what **actually shipped**, not what was locked at planning time. If the
plan changed mid-implementation, record the change and say so — do not quietly
write the new version as though it was always the plan.

Use the project's existing docs structure. Where it has none and the work taught
something durable, propose the smallest structure that fits rather than importing
another project's tree.

**Put each thing in its own home.** Most projects need this triage even when they
spell the folders differently:

- **A fact about one feature** → that feature's own entry.
- **A rule every screen obeys** → wherever design rules live, not one feature's
  page.
- **A technical rule cutting across features** (unit representation, data
  access, authorization) → wherever platform rules live.

A universal rule written into a single feature's doc is invisible to the next
feature that needed it, which is how the same decision gets made twice.

Each entry carries:

- **What it is** — a few lines in the user's language.
- **Where it lives** — entry-point files, so someone can find the code. This is
  also what lets a changed file be traced back to the feature that owns it.
- **Decisions** — calls that could have gone the other way, with the reason.
- **Invariants** — rules that bite whoever doesn't know them. Anything that cost
  time to discover belongs here, phrased as a rule, with the measurement or the
  failure it prevents so the next reader believes it.
- **Related** — its neighbours, typed, one clause each saying what flows across.
  **Write the other half into the neighbour in the same pass.**
- **Last verified** — the date, and what it was checked against. Update it every
  time you verify, whether or not the entry changed.

**Write back to the neighbours too, not just what you built.** The set is
already established: everything the walk reached, plus everything propagation
reached, minus what you confirmed unaffected. For each one, either update it or
**say plainly that it is unaffected** — a neighbour silently skipped is exactly
how the next person builds against a stale contract.

**A copy is cited by its doc.** When `/copy-adapt` left a `PARITY: <source>`
marker, the doc that owns the copy names the copy's path in *where it lives*,
and declares `copied-from` ⇄ `copied-to` with the source's doc — or says the
same doc owns both. The marker makes the copy findable from the code; the doc
edge makes it findable from the docs. The checker's PARITY classes report a
dead marker, a missing doc edge, and a copy no doc cites.

**A new feature gets a doc from the template and a line in the router.** Start
from `docs/_templates/feature.txt` (STATUS first, per surface, dated) and add
one line to `docs/README.md` — the router is the feature registry, so a feature
missing from it is one the next session will build a second time.

**Re-run the checker after writing (`kit.py check`), and read what it says about
the tree.**
Anything it reports as *uncommitted* under a doc you did not touch is a doc
whose code moved in this pass without it — re-verify it now, not after the
commit, because once committed the STALE check is the only thing left to
catch it.

**Verify before you build, not after.** If a doc and the code disagree, the code
wins: correct the doc first and **say it had drifted**. Never fold that
correction quietly into the write-back — a doc that was wrong is information the
user wants, and burying it hides how far the drift had spread.

**Edit the existing entry — never append a changelog.** Docs describe the system
as it is now; git records how it got here.

**Do not document:** colours, spacing, copy tweaks, refactors, bug fixes, or
anything an API reference already covers. If the work changed no behaviour and
taught nothing durable, **say the docs need no change** rather than inventing an
entry.

**Keep each entry to roughly a screen — and when it outgrows that, split it**
rather than letting it sprawl. A feature that has earned several pages becomes a
folder with an index and one file per sub-feature, registered in the router, with
each edge carried down to whichever sub-file actually owns it. A size rule with
no instruction for exceeding it just gets ignored, so treat the split as the
action, not the warning.

**When the user asks for the same thing twice, that is a preference, not an
instruction.** A design approach, an architectural choice, a way of laying
something out — log it the second time with what was asked and where it was
applied — in `docs/design/PREFERENCES.txt` (LOG). On the third, ask once
whether to make it standing. If yes, it goes into the design or platform doc it
belongs to — somewhere this checklist reads automatically — and is marked
STANDING in the preferences file with a pointer, so it is applied from then on
without being asked for again.

## Step 5 — Ship (only on explicit approval)

Take the commit identity, attribution rules, branch mapping and deploy path from
the SHIP section of `docs/PROJECT_PROFILE.txt` (and the project's `CLAUDE.md`,
which wins on conflict). Any of them still marked ASK is **asked, never
guessed** — the wrong author or branch is tedious to undo — and the answer is
written into the profile so it is asked once.

**Then, once — mention anything ready to land.** Shipping is when somebody is
already thinking about git, so it is the cheapest moment to raise a branch that
looks done and forgotten (see Step 0). One line naming the branch, how far ahead
it is, and whether a merge or a PR is the right route for this repo.

Say it once and drop it. If the answer is not now, it is not now — repeating it
every ship is how the whole check stops being read.
