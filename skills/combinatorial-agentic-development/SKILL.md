---
name: combinatorial-agentic-development
description: Plans and builds a feature whose product decisions are still open by treating the decision space (dimensions, options, constraints) as the input, then delivers it as stacked merge requests or pull requests with verified variants. Use this skill whenever an engineer lists alternative options or variants for a feature, says product has not decided yet, wants every variant planned or a decision tree, variant matrix or pairwise test matrix, asks for dependent or stacked MRs/PRs derived from options, or changes such a plan mid-flight ("new decision path", "add an option", "drop HubSpot", "emails can be HTML or text"), even if they never say "decision space".
license: MIT
compatibility: Requires Python 3.9+ and git. No other dependencies.
---

# Combinatorial Agentic Development

Why choose a product path when you can implement the whole decision space?

The engineer describes a feature and its open decisions. You keep one planning document per feature. It shows every option, the valid variants, a reduced decision tree, a plan of shared foundations plus per-option work, a test matrix, and a stack of dependent MRs. Planning and implementation are two separate phases with a sign-off in between.

The tool computes. You judge. Never count variants, check constraints, or pick stack parents in your head: the script does that deterministically, and a planning document with wrong numbers is worse than none.

## Setup

```bash
CAD="python3 <this skill directory>/scripts/cad.py"   # Python 3.9+, no dependencies
```

Planning documents live in `docs/variants/<feature>.md` unless the repository already has a place for plans. Read the repository's `AGENTS.md`, `CLAUDE.md` and contribution docs first; their rules for branches, commits and MRs win.

## Phase 1: plan

### 1. Turn the conversation into a spec change

The engineer may paste YAML, edit the spec block, or just talk ("emails can be HTML or text"). In every case, translate the request into a concrete spec change and read it back before anything is regenerated:

```text
Proposed spec change (not applied yet)
  + dimension email_format: html | text   (applies when pdf_delivery == email)
  + interaction pdf-after-capture: pdf_delivery == email and email_capture == after_test

Impact (from cad.py analyze)
  valid variants 42 -> 52, test scenarios 42 -> 52, nodes 13 -> 17
  started work affected: none

Questions (default in brackets)
  1. Which emails use the format: only the PDF email, or confirmations too? [only the PDF email]
```

Rules for the translation:

- Say where the change lands: a new dimension, a new option on an existing one, or a conditional dimension (`applies_when`). Refinements of one option ("emails can be HTML or text") are almost always conditional dimensions.
- Name every constraint you add. Never add one silently, even when it is obviously right.
- Ask only questions whose answer changes the spec, in one batch, each with a default.
- Options that do nothing (`none`, `disabled`, `off`) are no-ops automatically. Mark others with `noop: true`.

Spec syntax, constraint grammar and every field: [references/spec-format.md](references/spec-format.md).

### 2. Analyze before writing the document

For a new feature, write the spec to a scratch file. For an update, edit the ```` ```yaml cad-spec ```` block in the document. Then:

```bash
$CAD analyze <spec.yaml or plan.md>
```

The receipt shows theoretical combinations, combinations collapsed by `applies_when`, combinations removed by constraints, valid variants, scenarios, nodes and the stack. Put its numbers in the readback. If the status is `error`, explain the finding and propose a fix. If it is `needs confirmation`, show the reasons and the options it prints, then wait for the engineer's choice.

### 3. Write or update the document

After the engineer confirms:

```bash
$CAD new docs/variants/<feature>.md --spec <spec.yaml> --intent "<one paragraph, in the engineer's terms>"   # first time
$CAD render docs/variants/<feature>.md --note "<what changed and why, in a sentence>"
```

`render` rewrites only the generated region and the front matter, appends a changelog entry, flags restacks for started branches, and clears a previous sign-off when the spec changed. If the spec is invalid, the document is left untouched.

Document layout and ownership: [references/document-format.md](references/document-format.md).

### 4. Review and enrich

- **Review notes** (the document's `## Review notes` section): add semantic findings the tool cannot see. Examples: combinations that are valid but meaningless, two options that are really the same, a missing constraint, an interaction that will need glue code. Phrase each as a finding or a question. Propose spec changes; do not apply them without confirmation.
- **Repository enrichment** (the spec's `plan:` section): after reading the code, fill in `components`, `files`, `guidance` and better titles per node id. This is what turns the plan into something implementable. Parallel nodes must not share files; the tool warns when they do.
- **Verification** (the spec's `verify:` section): set `test` to the project's test command and `probe` to a command that reports which options it observes in the product for a given variant. Without a probe, nothing proves the options are wired in. See [references/verification.md](references/verification.md). Re-run `render`.

### 5. Ask for sign-off

Summarize the plan in a few lines (counts, MR count, anything that needs confirmation) and point the engineer to the document. Only when the engineer explicitly approves:

```bash
$CAD approve docs/variants/<feature>.md --by "<engineer name>"
```

The approval is bound to a hash of the spec. Any later spec change sends the document back to draft.

## Phase 2: implement

```bash
$CAD check docs/variants/<feature>.md          # must exit 0, otherwise stop and go back to phase 1
$CAD stack docs/variants/<feature>.md          # dry run of every step, in stack order
$CAD brief docs/variants/<feature>.md --next   # exact instructions for the next node
```

For each node in stack order:

1. Take the brief. It holds the branch command, scope, owned files, files not to touch, acceptance criteria and the commit format.
2. Create the branch, implement exactly that scope, run the tests, commit.
3. Never add commits to a branch that already has children. If you must, `verify` prints the restack.

After every lane, and always before calling the work done:

```bash
$CAD verify docs/variants/<feature>.md --integration --probe
```

`verify` checks that branches sit on their planned parents and contain their tips, merges everything into a temporary worktree, runs `verify.test`, and runs the probe for every targeted variant. The work is done when `verify` passes. Passing tests on each branch are not enough: options that were never wired into the product pass them too.

**Delegation.** Handing briefs to a cheaper model or a teammate is fine. Give one brief or one lane at a time, then run `verify` yourself. Never report a stack as done based on the implementer's summary.

**Progress.** Branch state comes from git. Record MR references with `$CAD mark <doc> <node> --status mr-open --mr '!42'`, only while the base branch is checked out, so feature branches never carry plan edits.

**Remote operations.** Local branches and commits are fine after approval. Pushing, opening MRs, force-pushing a restack and retargeting MRs are outward-facing: do them only when the engineer asks. `stack --write-descriptions .cad/mr` writes the MR bodies.

## Changes in flight

- **The decision space changes:** return to phase 1. `render` reports added and removed nodes, started branches that need a restack, open nodes whose contract changed ("needs update"), and plans a follow-up node (`base.r2`) for every merged node whose contract changed.
- **The code of a node changes:** run `$CAD impact <doc> <node>` first. Amend an open branch, then `$CAD restack <doc> <node>` (add `--execute` to run it locally) and `$CAD verify <doc> --integration --probe --only <node>`.
- **Never rewrite merged history.** Changes to merged nodes become follow-ups or normal new branches.
- **Land the trunk early.** Merging `base` and the abstractions first keeps later cascades short.

Details: [references/changes.md](references/changes.md), [references/stacking.md](references/stacking.md), [references/verification.md](references/verification.md).

## Implementation shape

Plans are built per option. Keep the code shaped the same way:

- **Foundation (`base`):** domain model, one configuration object with a key per dimension, validation that rejects the combinations the constraints remove, a composition root that discovers option modules at runtime, and the probe.
- **Abstraction (`dim.*`):** one interface per dimension (strategy, adapter, registry, or whatever the codebase already uses), registered by option id. Today's behavior stays the default. No-op options are real implementations.
- **Option (`opt.*`):** one implementation plus its registration, and a marker the probe can observe. If the interface must change, that belongs in the abstraction node.
- **Interaction (`ix.*`):** glue where options meet, kept at the composition root so each option still works alone.

Prefer configuration, strategies and feature flags over copied flows. Copying a flow per variant is the failure this skill exists to prevent.

## Generation modes

`generation.mode` picks the targeted variants. Implementation always covers the union of options in them; the mode mostly decides the test matrix.

| Mode | Targets | Use when |
|---|---|---|
| `exhaustive` | every valid variant | the space is small, or every variant ships |
| `pairwise` | every reachable pair of option values | the space is large and you want strong, cheap test coverage |
| `twise` | every reachable combination of `strength` values | pairwise is too weak for risky interactions |
| `selected` | variants listed in the spec | only some variants will ship |

Never describe pairwise or t-wise results as covering every product. The document states how many configurable variants have no dedicated scenario; repeat that number when you summarize. Trade-offs: [references/modes.md](references/modes.md).

## Guardrails

- Show theoretical, removed and valid counts before proposing work. They come from `analyze`, never from mental math.
- When a limit is exceeded, present the options the tool prints and wait. Raising a limit is the engineer's call.
- Enumeration above `max_enumeration` is refused. Suggest splitting the feature or using `applies_when`.
- Contradictory constraints, dead options, constraints that never fire and redundant constraints are reported by the tool. Explain them in plain words and suggest a fix.
- No branches before `check` passes. No remote operations without an explicit request.
- Nothing is done until `verify --integration --probe` passes.
- Branch names, commits and MR text describe the work. Never mention the agent, AI assistance or tooling authorship.
- Keep the premise light in conversation if the engineer enjoys it, and keep the document factual.

## Command reference

| Command | Purpose |
|---|---|
| `analyze <spec or doc> [--json] [--variants]` | Count, validate and plan without writing anything |
| `new <doc> --spec <file> [--intent TEXT]` | Create a planning document |
| `render <doc> [--note TEXT]` | Regenerate the plan, append changelog, flag restacks |
| `approve <doc> --by NAME` | Record sign-off bound to the current spec |
| `check <doc>` | Exit 0 only if the current spec is approved |
| `stack <doc> [--platform gitlab/github/none] [--preview] [--write-descriptions DIR] [--json]` | Dry-run steps in stack order |
| `brief <doc> [<node> or --next]` | Self-contained instructions for one node |
| `verify <doc> [--integration] [--probe] [--only NODE] [--json]` | Compare the plan with git, integration and behavior |
| `impact <doc> <node> [--json]` | Blast radius of changing a node: dependent code, stacked branches, scenarios |
| `restack <doc> [<node>] [--execute]` | Rebase stale branches and everything built on them, parents first, local only |
| `mark <doc> <node> --status planned/branched/mr-open/merged [--mr REF] [--restacked] [--updated]` | Record MR references and progress (base branch only) |

JSON output follows [references/analysis.schema.json](references/analysis.schema.json); specs follow [references/spec.schema.json](references/spec.schema.json).
