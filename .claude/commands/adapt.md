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

## Step 0 — Establish source and target

Before copying anything:

1. **Locate the canonical source.** Copy from the most-hardened version, never a
   half-finished sibling. If the repo has several, say which you picked and why.
   When the working tree sits on a feature branch, read the source from the
   mainline (`git show <main-branch>:<path>`) rather than whatever is checked out.
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

## Residue sweep (the number-one failure mode)

After adapting, actively hunt and kill every source-domain leftover: labels, copy,
routes, icons, analytics event names, i18n keys, test fixtures, comments, and
type names. The adapted code must reference the source domain **nowhere**.

This is an explicit pass you actually run, not an assumption.

## Divergence

When the target doesn't map one-to-one, **stop and surface it for a decision** —
don't force fidelity. Mechanical swaps (route, model, label) you just do; genuine
product forks you raise before writing them.

## Anti-rot

- Reuse the shared layer when something is genuinely common, instead of copying.
- **Rule of three:** the second or third time the same thing gets copied, flag it
  for extraction into the shared layer.
- **Bug parity:** if this copy reveals or fixes a bug, check the siblings it was
  copied from or alongside, and offer to back-port.
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
