"""Cascade restacks: bring a stale branch and everything built on it up to date.

Every branch is rebased with `git rebase --onto <parent> <old base> <branch>`,
parents first. The old base is the recorded fork point (refs/cad/base/<branch>)
or, without one, the merge base computed before anything moves. That way only
the branch's own commits are replayed, even when the parent was amended or
squash-merged.
"""

from dataclasses import dataclass

from . import gitops
from .verify import Report, _effective_parent, check_state, fork_ref, old_base, subtree

__all__ = ["Step", "plan", "execute"]


@dataclass
class Step:
    node: str
    branch: str
    onto: str
    old_base: str

    @property
    def commands(self):
        return [
            f"git rebase --onto {self.onto} {self.old_base[:12]} {self.branch}",
            f"git update-ref {fork_ref(self.branch)} {self.onto}",
        ]


def plan(repo, stack, node=None):
    """Steps to restack `node`'s subtree, or every stale subtree when node is None."""
    report = Report()
    check_state(repo, stack, report)
    statuses = report.nodes
    if node:
        roots = [node]
    else:
        roots = [i.node for i in report.issues if i.check == "state" and i.node and "is stale" in i.text]
    affected = set()
    for root in roots:
        affected.update(n for n in subtree(stack, root) if statuses.get(n) == "branched")
    steps = []
    for nid in stack.order:
        if nid not in affected:
            continue
        branch = stack.placements[nid].branch
        parent = _effective_parent(stack, statuses, nid)
        steps.append(Step(nid, branch, parent, old_base(repo, branch, parent)))
    return steps


def execute(repo, steps):
    """Run the steps locally. Stops at the first conflict. Never pushes."""
    if gitops.git(repo, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        raise gitops.GitError("the working tree has uncommitted changes; commit or stash them first")
    original = gitops.current_branch(repo)
    for n, step in enumerate(steps, 1):
        proc = gitops.git(repo, "rebase", "--onto", step.onto, step.old_base, step.branch, check=False)
        if proc.returncode != 0:
            return False, (
                f"[{n}/{len(steps)}] rebasing `{step.branch}` onto `{step.onto}` stopped with conflicts.\n"
                "Resolve them, run `git rebase --continue`, then run `cad.py restack` again to finish the cascade."
            )
        gitops.git(repo, "update-ref", fork_ref(step.branch), step.onto)
    if original:
        gitops.git(repo, "switch", "-q", original, check=False)
    return True, f"Restacked {len(steps)} branch(es)."
