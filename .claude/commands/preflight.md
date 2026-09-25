---
description: Run any task under a general execution checklist — orient in the active repo, tier-1 standards, per-point pre-flight ritual, then wait for go
argument-hint: <paste the task / feature instruction>
---

You are implementing the following under the **General Execution Checklist**:

> $ARGUMENTS

Apply the tier-1, primary-source standards below. **Every project-specific
detail — stack, docs location, tokens, units, branches, commit identity, gate
commands — is discovered from the active repo, never assumed.** Where a standard
and a repo convention collide, the repo convention wins and you flag it.

## Step 0 — Orient in THIS repo (mandatory, before any code)

Do not carry conventions across from another project. Establish, for the repo you
are actually in:

1. **Read the project's own instructions** — `CLAUDE.md`, `AGENTS.md`, or
   `README.md` at the repo root. These outrank anything in this checklist.
2. **Find the knowledge base.** Look for `docs/README.md` (or an index the root
   doc points to). If it exists, treat it as a router: read the router, then open
   **only** the entries this work touches. If there is no docs tree, say so — that
   is a real finding and it means you are working without written precedent.
3. **Identify the surfaces this work touches** and the rulebook for each:
   - Detect the stack from manifests — `package.json`, `pubspec.yaml`, `go.mod`,
     `pyproject.toml`/`requirements.txt`, `Cargo.toml`.
   - For each, name the governing authority you will actually apply (e.g. the
     official architecture guide for that framework, the language's idiom guide).
   - **Pin versions from the lockfile, not memory.** A major version you assumed
     is how breaking changes get shipped. If a framework's major version has
     breaking changes, read its bundled docs before writing code for it.
4. **Note the project's own conventions** so you can obey them: money/unit
   representation, error envelope, naming, folder layout, theme tokens, auth model.

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

## The standards (apply throughout)

1. **Reuse & copy-adapt** — search the repo for the closest existing thing before
   writing anything new; reuse bottom-up (shared primitives → composed widgets →
   feature code). Use `/adapt` to port it, changing only what the new domain
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

## Step 3 — Update the docs (after it works, before reporting done)

Write up what **actually shipped**, not what was locked at planning time. If the
plan changed mid-implementation, record the change and say so — do not quietly
write the new version as though it was always the plan.

Use the project's existing docs structure. Where it has none and the work taught
something durable, propose the smallest structure that fits rather than importing
another project's tree.

Each entry carries:

- **What it is** — a few lines in the user's language.
- **Where it lives** — entry-point files, so someone can find the code.
- **Decisions** — calls that could have gone the other way, with the reason.
- **Invariants** — rules that bite whoever doesn't know them. Anything that cost
  time to discover belongs here, phrased as a rule, with the measurement or the
  failure it prevents so the next reader believes it.

**Edit the existing entry — never append a changelog.** Docs describe the system
as it is now; git records how it got here.

**Do not document:** colours, spacing, copy tweaks, refactors, bug fixes, or
anything an API reference already covers. If the work changed no behaviour and
taught nothing durable, **say the docs need no change** rather than inventing an
entry.

Keep each file to roughly a screen.

## Step 4 — Ship (only on explicit approval)

Take the commit identity, attribution rules, branch mapping and deploy path from
the project's `CLAUDE.md`. If they are not written down, **ask rather than
guessing** — the wrong author or branch is tedious to undo.

**Shipping includes what people download, not just what deploys.** A project
that hands out an installer has a second artifact that must not fall behind the
code: when a merge to the main branch changes an app that people install,
publishing a fresh build of it is part of shipping, and the page offering that
download must show the new one without anyone redeploying the site.

Check this before calling the work shipped:

- The build runs from CI on the merge, not from someone's laptop. A build made
  by hand is a build nobody else can reproduce, and it stops happening the week
  its author is busy.
- It builds on the platforms people actually use. Neither half of a desktop app
  cross-compiles: the Windows build comes off a Windows runner, the macOS build
  off a macOS runner.
- It publishes to a stable location the site reads, so a new build needs no
  redeploy — and the site checks the file is there rather than linking blindly.
- Trigger it on the paths that can change the app, not on every commit.
  Rebuilding an identical binary because a doc changed wastes the runners and
  teaches everyone to ignore the pipeline.
- Unsigned builds are the normal case for a student or internal project. Say on
  the download page what the operating system will warn and what to click, or
  the download is useless to whoever is not expecting it.

In this repository there is no published download any more (2026-09-25): the
app is installed from a terminal with `node scripts/install.mjs`, and
`.github/workflows/desktop-install.yml` runs that command on an Apple-silicon
Mac, an Intel Mac and Windows — see `docs/features/development/releases.txt`.
