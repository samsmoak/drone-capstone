---
description: Copy an existing screen/feature/module into a new domain or platform, adapting only what the target forces to change
argument-hint: <source screen/feature> → <target workspace/domain> [+ adaptation notes]
---

Apply the **copy-and-adapt** principle to this request:

> $ARGUMENTS

## Core rule

Copy the existing code **as-is** and adapt **only** what the target forces to
change. Reuse beats reinvention — never redesign from scratch. The design
decisions are already encoded in the source; your job is faithful transcription
plus the minimum adaptation, applied across every layer the feature spans.

## Step 0.0 — The kit: make sure what this skill relies on exists

A copy is only findable later if the project can read its provenance marker and
tie it to a doc — which needs the docs tree, the doc template and the graph
checker. None of that may be assumed. Run first, every time:

```
python3 ~/.claude/feature-kit/kit.py doctor
```

Anything `[MISSING]` → `python3 ~/.claude/feature-kit/kit.py init` (creates only
what is absent, never overwrites), then show the user what was created and the
repo list it detected, to be confirmed. Checker `OUTDATED` → `kit.py upgrade`.
If the kit itself is absent, say so and do its checks by reading.

**A PLATFORM PORT (or any copy into another repo) needs a parity ledger** in the
target repo — the item-by-item status and the source→target translation map.
If the doctor lists none for this port, create it before copying:

```
python3 ~/.claude/feature-kit/kit.py parity-ledger <target-repo> "<Area> port" --source <source-repo-name>
```

and fill its §0 translation map on the first port (derived by reading both
repos). Every later port updates the same ledger — never a second one.

## Step 0 — Establish source and target

Before copying anything:

1. **Locate the canonical source.** Copy from the most-hardened version, never a
   half-finished sibling. If the repo has several, say which you picked and why.
   When the working tree sits on a feature branch, read the source from the
   mainline (`git show <main-branch>:<path>`) rather than whatever is checked out.

   **Check no branch is ahead of the mainline for that source first.** A copy
   inherits whatever it was taken from, and a fix sitting unmerged is a fix the
   copy silently does without — so the new feature is born carrying a bug that
   was already solved somewhere nobody looked. This is worse here than in
   ordinary work: a stale read gets fixed when someone notices, while a stale
   COPY becomes a second place to fix it forever.

   Say which branch each piece came from, and its date. If a branch does carry
   newer work than the mainline, **stop and ask** — landing that first is almost
   always cheaper than adapting the old version and reconciling twice.
2. **Read the target's own rules** — its `CLAUDE.md`/`AGENTS.md`, its tokens, its
   folder layout. The copy must land looking like the target, not like the source.
3. **Decide which mode this is:**
   - **Domain port** — same platform, different subject matter. Vocabulary,
     endpoints and business rules change; structure and idiom stay.
   - **Platform port** — same subject matter, different technology. Vocabulary,
     endpoints and permissions stay *identical*; only platform idioms change.

   Say which mode you are in. They have opposite adaptation axes, and confusing
   them produces either a clone that doesn't fit or a rewrite that loses the
   design.

## Copy (fidelity-first)

The source is the source of truth. Reproduce exactly:

- **Visual** — theme/colour tokens, spacing, padding, alignment, sizing.
- **Structure** — component tree, layout, composition, element order.
- **Code shape** — naming, file/folder structure, state wiring, and the
  loading/empty/error/content handling.

Do not re-decide, re-style or "improve" any of it unless asked.

## Adapt (only what the target forces)

- New-domain routes and endpoints.
- Models/DTOs and their fields.
- Domain vocabulary — labels, copy, icons.
- Domain business logic and validation.
- The data source the repository/provider reads from.

Everything the target does not force to change stays byte-for-byte identical.

## Scope

Port the **whole** feature, not just its screen: UI, state management, data
access, and the server-side module (model/validation, routes, permission checks)
where one exists. Keep any API contract document in sync in the same pass.

## Platform-port mode

When the target is a different technology, build the **translation table first**
and put it in your plan — source construct on the left, target construct on the
right, one row per recurring pattern (route, screen, component, async data,
global state, modal, toast, typography, colour tokens, empty/error states,
permission gates, i18n keys, realtime subscriptions).

Derive the table from what the target repo **already does**, by reading it — never
from memory of how such things are usually done.

**Fidelity in platform-port mode** means: same information hierarchy, element
order, copy, validation rules, permission gating, and async states — rendered
through the target's own token and component system. It does **not** mean a pixel
clone of the source's chrome. Target-native idioms (hover and focus states,
keyboard navigation, wider layouts, drawers instead of push navigation, or the
reverse) are mandatory adaptations, not drift.

**Keep identical across a platform port:** i18n keys (copy the translated strings
verbatim), permission/capability names, endpoint paths, and domain vocabulary. A
mismatch here silently breaks gating or translation.

**No direct equivalent?** Adapt, don't drop — and mark it explicitly in your
report (`[ADAPTED]` / `[N/A]`) so the gap is visible rather than forgotten.

## Record where it came from

A copy that does not say what it was copied from is invisible the next time
something changes in its source — which is the moment it mattered.

- **Leave a provenance marker in the code**, in a form that can be searched
  later, not only prose: `PARITY: <source path>` in the file's header comment.
  A sentence saying "adapted from the transit card" reads well and greps badly;
  write both. **The exact form is the contract**: a repo-relative path, prefixed
  with the source repo's folder name when the copy crossed repos
  (`PARITY: other-repo/lib/x.dart`), so a checker can resolve it. A marker that
  names a path that no longer exists is a broken edge, not history — fix it
  when the source moves.
- **Give the new feature a doc entry** if the project keeps one — with what it
  is, where it lives (**naming the copy's own path**, or the marker is invisible
  from the docs), and a `copied-from` edge naming the source. Carry the
  old→new vocabulary map into it. That map costs real time to rediscover, and it
  is the thing nobody thinks to write down.
- **Write the other half of the edge** into the source's entry (`copied-to`), so
  the relationship is visible from both ends.

Without this, anything built by copying is unreachable from the source — the
graph has a node nobody can find.

**Enforced, not remembered.** Run `python3 ~/.claude/feature-kit/kit.py check`
before calling the copy done. Its PARITY class (a dead source, or copy and
source docs with no copy edge) and PARITY COPY UNCITED (a copy no doc names)
for your files are part of the done-bar. A new doc for the copy starts from
`docs/_templates/feature.txt` and gets its line in the `docs/README.md` router.

## Residue sweep (the number-one failure mode)

After adapting, actively hunt and kill every source-domain leftover: labels, copy,
routes, icons, analytics event names, i18n keys, test fixtures, comments, and
type names. The adapted code must reference the source domain **nowhere**.

This is an explicit pass you actually run, not an assumption.

**In code, sweep everything. In prose, sweep only what points at the wrong
place** — paths, endpoints, identifiers, type names. A doc that explains the new
domain *by contrast with the source* ("a room-night is not a seat") is doing its
job, not leaking. Deleting that comparison removes the clearest explanation of
why the new thing is shaped the way it is.

## Divergence

When the target doesn't map one-to-one, **stop and surface it for a decision** —
don't force fidelity. Mechanical swaps (route, model, label) you just do; genuine
product forks you raise before writing them.

## Anti-rot

- Reuse the shared layer when something is genuinely common, instead of copying.
- **Rule of three:** the second or third time the same thing gets copied, flag it
  for extraction into the shared layer — and **write the flag down** in
  `docs/design/components.txt` §EXTRACTION CANDIDATES (the kit creates it), not
  only in conversation, where it is lost by the next session. Extraction is also what permanently ends the copy's maintenance
  cost: once shared, a change reaches every user for free.
- **Bug parity:** if this copy reveals or fixes a bug, back-port it to the
  siblings. **Find them from the provenance markers rather than memory** — search
  for what shares this source (`grep -rn "PARITY: <source path>"` across the
  profile's repos), and for what this source was itself copied from. Record the
  fix as a `[FIXED]` line in the parity ledger when the copy crossed repos.
  Name the ones you checked, including the ones you decided were unaffected and
  why; "I checked the siblings" without naming them is indistinguishable from
  not having looked.
- Theme through the target's tokens — never hardcode a value the token system
  already owns.

## Reporting

Present the result as **"what changed and why"** — the adaptation delta and the
old→new vocabulary map — not the whole file to re-read. Cite the exact source file
for each piece you copied.

## Done-bar

The target project's own gates, clean — build, lint, type check and tests. Plus:
the feature actually driven against the new data source with no residual calls to
the source domain, every theme the project supports checked, and the source's
tests adapted too, not just its screens.
