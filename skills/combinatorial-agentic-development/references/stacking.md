# Stacked MRs

## From dependencies to branches

Each plan node depends on other nodes:

- `dim.<d>` on `base`, and on the enabling option when `applies_when` is set.
- `opt.<d>.<o>` on `dim.<d>`, and on whatever a `requires` constraint triggered by `<d> == <o>` asks for: the option node for `x == v`, the abstraction `dim.<x>` for looser rules (`!=`, `in`, negations). `excludes` and `never` only validate and add no dependency.
- `ix.<id>` on the option nodes named in its `when` expression.

Redundant edges are removed (transitive reduction). A git branch has one parent, so placement turns this graph into a tree:

- **tree** (default): each node sits on its deepest dependency. If dependencies live on different lanes, the shallower lane is grafted onto the deeper one when every moved node keeps its own dependencies, and the node's "Why" row says so. If grafting is impossible, the node starts from the base branch in a later **wave**, after its dependencies merged.
- **linear**: every node sits on the previous one in dependency order. Simple to review, slow to merge.

Placement respects progress. Merged nodes count as part of the base branch. Lanes that contain branched or open work are never moved; the tool prefers a later wave.

Merge order is the order of the stack table. Parents always come first.

## Dry run

`cad.py stack <doc>` prints the steps and executes nothing:

```bash
git switch -c lead-capture-flow/pdf-delivery-email lead-capture-flow/pdf-delivery
# implement opt.pdf_delivery.email, run its tests, commit
git push -u origin lead-capture-flow/pdf-delivery-email
glab mr create --draft --source-branch lead-capture-flow/pdf-delivery-email \
  --target-branch lead-capture-flow/pdf-delivery --title 'PDF delivery: email' \
  --description "$(cat .cad/mr/lead-capture-flow__pdf-delivery-email.md)" --yes
```

`--write-descriptions DIR` writes the MR bodies. `--json` returns the same steps for tooling. Without approval the command refuses unless `--preview` is given. Without a remote, root branches start from the local base branch and push and MR steps are left out. Branch progress is read from git (a branch that exists is `branched`, one contained in the base branch is `merged`).

Use `cad.py brief <doc> --next` for the instructions of the next node and `cad.py verify` to check the result; see [verification.md](verification.md).

## Restacking

`render` compares each started node's recorded parent with its new one and records `restack_from`. `stack` then prints:

```bash
git fetch origin
git rebase --onto <new parent> <old parent> <branch>
git push --force-with-lease origin <branch>
glab mr update <iid> --target-branch <new parent>     # or: gh pr edit <number> --base <new parent>
```

When a parent merges (squash merges included), its children move to the base branch with `git rebase --onto origin/main <parent branch> <child>` and a retarget. Run these only when the engineer asks, then `cad.py mark <doc> <node> --status mr-open --restacked`.

## GitHub and GitLab integration

Version 1 prints commands and records progress; it never talks to a remote. The data needed for full automation is already in the document: branch, parent, merge order, MR reference and status per node. Integration paths, in increasing order of effort:

1. **Run the printed commands.** `glab` and `gh` both accept a target branch per MR, which is all a stack needs. The agent runs them one node at a time on explicit request and calls `mark` after each.
2. **Stacking tools.** git-spice (`gs branch create`, `gs stack submit`), Graphite (`gt create`, `gt submit`), git-town (`git town append`, `git town sync`) and GitLab's experimental `glab stack` already handle restacking and retargeting. An adapter maps the stack table to their commands and reads their state back into `mark`.
3. **Native git.** For linear stacks, `git rebase --update-refs` (git 2.38+) moves every branch in one command.
4. **Status sync.** A small script reads MR state through `glab api` or `gh api` and updates node status, so merged parents trigger retarget steps automatically.
5. **CI guard.** A job runs `cad.py check` on MRs that touch `docs/variants/` and fails when a plan changed without renewed approval.

Constraints for any integration: keep the dry run as the default, never push or retarget without an explicit request, and keep branch names and MR text free of tool or agent attribution.
