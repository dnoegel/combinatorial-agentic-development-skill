# Stacked MRs

## From dependencies to branches

Each plan node depends on other nodes:

- `dim.<d>` on `base`, and on the enabling option when `applies_when` is set.
- `opt.<d>.<o>` on `dim.<d>`, and on whatever a `requires` constraint triggered by `<d> == <o>` asks for: the option node for `x == v`, the abstraction `dim.<x>` for looser rules (`!=`, `in`, negations). `excludes` and `never` only validate and add no dependency.
- `ix.<id>` on the option nodes named in its `when` expression.

Redundant edges are removed (transitive reduction). A git branch has one parent, so placement turns this graph into a tree:

- **tree** (default): each node sits on its deepest dependency. If its dependencies live on different lanes, one lane is grafted under the other, and the node's "Why" row says so. Of the possible grafts, the tool picks the one that stacks the fewest nodes on code they do not need. If that is more than `stack.max_coupling` nodes (default 2), or no graft keeps every moved node's dependencies, the node starts from the base branch in a later **wave**, after its dependencies merged.
- **linear**: every node sits on the previous one in dependency order. Simple to review, slow to merge.

Placement respects progress. Merged nodes count as part of the base branch. A branch that already exists keeps the parent it was built on (recorded as `onto` in the front matter) as long as that parent still covers its dependencies, and lanes with started work are never grafted elsewhere.

Merge order is the order of the stack table. Parents always come first.

## Dry run

`cad.py stack <doc>` prints the steps and executes nothing. Nodes that already have a branch are listed with their status from git; new nodes get their commands:

```bash
git switch -c lead-capture-flow/pdf-delivery-email lead-capture-flow/pdf-delivery
git update-ref refs/cad/base/lead-capture-flow/pdf-delivery-email lead-capture-flow/pdf-delivery
# implement opt.pdf_delivery.email (cad.py brief <doc> opt.pdf_delivery.email), run its tests, commit
```

Children of merged parents start from the base branch. Without a remote, root branches start from the local base branch instead of `origin/<base>`. `--json` returns the same steps for tooling. Use `cad.py brief <doc> --next` for the instructions of the next node and `cad.py verify` to check the result; see [verification.md](verification.md).

## Restacking

`verify` reports a stale branch together with everything built on it, and `cad.py restack <doc> [<node>]` prints the cascade, parents first:

```bash
git rebase --onto <parent> <recorded fork point> <branch>
git update-ref refs/cad/base/<branch> <parent>
```

`--execute` runs it locally and stops at the first conflict. Pushing restacked branches (`git push --force-with-lease`) and retargeting their MRs happen only when the engineer asks. Details: [changes.md](changes.md).

## GitHub and GitLab

The tool never talks to a remote. Everything needed to open the stack is available: branch, target and merge order in the document, and a ready MR description per node from `cad.py brief`. `glab mr create --target-branch <onto>` or `gh pr create --base <onto>` is all a stack needs. Stacking tools such as git-spice, Graphite, git-town or `glab stack` can take over restacking and retargeting if a team already uses them.
