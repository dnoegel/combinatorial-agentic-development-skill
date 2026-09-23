# Changes in flight

Decisions change while the stack is half built. There are two kinds of change, and they are handled differently.

## 1. The decision space changes (the spec)

Someone adds an option, drops one, adds a constraint, or a dimension becomes conditional. Handle it like any spec change: read back, `analyze`, confirm, `render`. `render` reports:

- **Added and removed nodes.** Branches that exist for nodes that are no longer planned are listed; close or revert them on purpose.
- **Restack needed.** A started branch whose planned parent changed is listed with its old and new parent; `cad.py restack` moves it.
- **Changed after work started.** Every node has a *contract*: its decisions, dependencies, scope and acceptance criteria. `render` keeps a snapshot for every started node. When the contract of a branch that is not merged yet changes, the changelog names the node and the exact difference. Amend the branch, then restack its children.
- **Follow-up.** When the contract of a **merged** node changes, `render` plans a follow-up node (`base.r2`, `dim.style.r3`, ...) with the difference as its acceptance criteria. It starts from the base branch, and planned nodes that build on the original now build on the follow-up. Merged history is never rewritten.

## 2. The code of a node changes (no spec change)

A reviewer asks for changes in `base`, or an abstraction's interface turns out wrong. Start with the blast radius:

```bash
cad.py impact <doc> <node>
```

It lists the code that depends on the node (it must keep working, and it must adapt when an interface changes), the branches stacked on it (they must be restacked), the scenarios to re-check, and what to do given the node's status.

- **Not branched yet:** change the plan or the spec.
- **Branched or MR open:** amend the branch (new commits or `--amend`), then:

  ```bash
  cad.py restack <doc> <node>             # prints the cascade, parents first
  cad.py restack <doc> <node> --execute   # runs it locally, stops at the first conflict
  cad.py verify <doc> --integration --probe --only <node>
  ```

- **Merged:** do not rewrite it. If the contract changes, change the spec and let `render` plan the follow-up. If the contract stays the same (a bug fix), add a normal commit on a new branch from the base branch.

When an abstraction's interface changes, every option of that dimension appears in `impact` as code that depends on it. The contract tests from the abstraction node and the probe prove they followed.

## Why restacks do not replay the wrong commits

Each branch remembers the parent commit it was built on in a metadata ref, `refs/cad/base/<branch>`. `stack` and `brief` include the command that records it, and `verify` refreshes it whenever a branch is up to date. `restack` rebases with `git rebase --onto <parent> <recorded fork point> <branch>`, so only the branch's own commits are replayed, even when the parent was amended, rebased or squash-merged. Without a recorded fork point it falls back to the merge base, which is right unless the parent was rewritten.

`verify` reports a stale branch together with every branch built on it, so a change on `base` shows the whole cascade at once instead of one level per run.

## Keep cascades short

A change to `base` in a deep, unmerged stack touches every branch. That cost is inherent to stacking. Keep it small:

- **Land the trunk early.** Merge `base` and the abstractions before most options. After that, a change to the foundation is a normal commit on the base branch, and each option rebases once, onto the base branch.
- **Keep the tree shallow.** The default tree layout puts options side by side under their abstraction; avoid `layout: linear` for large spaces.
- **Put interfaces in abstractions, not options.** An interface change then lives in one node, and `impact` lists exactly the options that must follow.
