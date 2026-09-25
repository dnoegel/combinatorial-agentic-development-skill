# Planning document format

One Markdown file per feature, usually `docs/variants/<feature>.md`. It is reviewed like code. See [../../../examples/lead-capture-flow.md](../../../examples/lead-capture-flow.md) for a full example.

## Layout and ownership

| Part | Owner | Notes |
|---|---|---|
| Front matter | tool | revision, spec hash, counts, branch layout, planned follow-ups |
| `# Title` and tagline | engineer | written once by `new` |
| `## Intent` | engineer | what the feature is for, in the engineer's words |
| `## Review notes` | agent | semantic findings and open questions, phrased for review |
| `## Spec` | engineer or agent | the canonical ```` ```yaml cad-spec ```` block; changes are read back and confirmed first |
| Generated region | tool | between the `cad:generated` markers; rewritten by every `render` |
| `## Changelog` | tool | newest first; the note passed to `render` becomes the entry text |

Edits inside the generated region are lost on the next `render`. Everything else is preserved. Progress (which branches exist or are merged) is not stored in the document; the tool reads it from git.

## Front matter

```yaml
cad: 1
feature: lead-capture-flow
revision: 2                 # bumps when the spec hash changes
spec_hash: 1f0c9a3e5b21     # of the parsed spec, so comments and formatting do not count
counts: {theoretical: 108, valid: 52, scenarios: 52, nodes: 18}
nodes:                      # where each branch goes; started branches keep their recorded parent
  opt.email_capture.after_test:
    branch: lead-capture-flow/email-capture-after-test
    onto: lead-capture-flow/email-capture
followups:                  # revisions of merged nodes whose contract changed
  - id: base.r2
    of: base
    revision: 2
    changes: ["+ options: email_format: html, text"]
```

Contract snapshots of started nodes live in an HTML comment at the very end of the document (`<!-- cad:contracts ... -->`). They are invisible when rendered and let `render` detect what changed; see [changes.md](changes.md).

## Generated region

1. **Decision space**: the counts table and any confirmation reasons with options.
2. **Decision tree**: a Mermaid diagram of the valid variants (see below).
3. **Dimensions**: options with no-op, dead and not-targeted markers, plus `applies_when`.
4. **Constraints**: each rule with how many combinations it removes, how many only it removes, and findings.
5. **Findings**: tool findings (errors, warnings, info).
6. **Implementation plan**: node counts, the MR stack diagram, the stack table (merge order), and one collapsible block per node with decisions, scope, dependencies and why they exist, components and files, branch and target, tests, scenarios, and acceptance criteria. MR descriptions come from `cad.py brief`.
7. **Test matrix**: mode, an explicit statement of what the matrix does and does not cover, coverage numbers for pairwise and t-wise, and the scenario table (folded when long).

## Mermaid conventions

**Decision tree.** A reduced decision diagram: one node per remaining decision, edges labeled with options, and every left-to-right path is exactly one valid variant. Branches whose continuations are identical are merged, and decisions that do not apply are skipped. The lead-capture example draws all 42 variants with 8 decision nodes. When the reduced diagram would exceed 60 nodes it is omitted and the tables remain complete. An excerpt:

```mermaid
flowchart LR
  n0(["Channel"])
  n1(["PDF delivery"])
  n2(["Email capture"])
  n3(["CRM sync"])
  done(["valid variants"])
  n0 -->|"website / landing_page"| n1
  n1 -->|"email"| n2
  n2 -->|"before_test / after_test"| n3
  n3 -->|"hubspot / none"| done
```

**MR stack.** Top-down from the base branch. Node labels are the MR title plus the node id. A dotted edge from the base branch marks a later wave.

Diagrams use only flowchart syntax with quoted labels, so GitHub, GitLab and most Markdown viewers render them.
